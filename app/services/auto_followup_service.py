# app/services/auto_followup_service.py
"""
Авто-прозвон молчащих клиентов.

Сценарий:
  /start и час тишины            -> авто-сообщение #1, стадия => «ждём ответ»
  сутки тишины после #1          -> авто-сообщение #2
  сутки тишины после #2          -> стадия => «ревизия/отказ»

Оба шага после первого живут в одном воркере: раньше это были два цикла,
которые каждые два часа независимо вычитывали одну и ту же стадию.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from sqlalchemy import and_, select, update

from app.config import BITRIX_FIELD_TG_ID_DEAL
from app.db.models import AutoFollowupState, TGUser
from app.db.session import async_session_maker
from app.integrations.bitrix.client import BitrixClient
from app.services.message_formatters import truncate_for_bitrix
from app.services.bitrix_stages import (
    STATUS_AFTER_FIRST_PING,
    STATUS_INCOMING,
    STATUS_REVISION,
    build_stage_id,
    status_from_stage_id,
)

logger = logging.getLogger(__name__)
bitrix = BitrixClient()

# -------------------- Тайминги --------------------

FIRST_PING_AFTER = timedelta(hours=1)
SECOND_PING_AFTER = timedelta(hours=24)
LOSE_AFTER = timedelta(hours=24)

FIRST_PING_INTERVAL_SECONDS = 3600
FOLLOWUP_INTERVAL_SECONDS = 7200

# -------------------- Тексты авто-сообщений --------------------

MSG1_TEMPLATE = (
    "Здравствуйте, <b>{name}</b>! 👋\n\n"
    "Вам пишет сотрудник проекта <b>WhaleTrade</b>.\n"
    "Благодарим вас за интерес к нашему ресурсу.\n\n"
    "Заметил, что вы пока не забрали наш авторский бесплатный мини-курс "
    "по трейдингу. Он поможет вам быстро разобраться, "
    "как устроена торговля и как мы выстраиваем системную работу на рынке.\n\n"
    "Если вам ближе автоматическая торговля — "
    "мы также можем предоставить тест нашего робота <b>WhaleTrade AI</b> "
    "на демо-счёте без обязательств.\n\n"
    "Напишите в ответ одним словом 👇\n"
    "• <b>курс</b> — если хотите получить обучение\n"
    "• <b>советник</b> — если интересен робот\n\n"
    "Или свяжитесь со мной напрямую @WhaleTradeSupport "
    "я подробно объясню все детали работы."
)

MSG2_TEMPLATE = (
    "Доброго времени суток! 😊 Это менеджер WhaleTrade.\n\n"
    "Возможно, вы не успели ответить на предыдущее сообщение — понимаю, "
    "предложений на рынке сейчас действительно много.\n\n"
    "Мы ничего не навязываем и не обязываем. "
    "Предлагаем бесплатно ознакомиться с нашими продуктами и форматом работы.\n"
    "Вы сможете спокойно оценить подход и понять, подходит ли он вам.\n\n"
    "Если интересно — просто отправьте цифру в ответ 👇\n\n"
    "1️⃣ Мини-курс по трейдингу\n"
    "2️⃣ Авторский индикатор спроса и предложений\n"
    "3️⃣ Тест полностью автоматического робота WhaleTrade AI\n"
    "4️⃣ Общая консультация по торговле\n\n"
    "Выберите удобный вариант — и я отправлю подробности."
)


# ============================================================
# имя клиента
# ============================================================


async def _get_client_name(bot: Bot, tg_id: int) -> str:
    """Имя для приветствия: Telegram → БД → 'друг'."""
    try:
        chat = await bot.get_chat(tg_id)
        first = (getattr(chat, "first_name", None) or "").strip()
        if first:
            return first
    except Exception:
        pass

    try:
        async with async_session_maker() as session:
            user = await session.scalar(select(TGUser).where(TGUser.tg_id == tg_id))
        if user and (user.tg_firstname or "").strip():
            return user.tg_firstname.strip()
    except Exception:
        pass

    return "друг"


async def _get_tg_client_identity(bot: Bot, tg_id: int) -> str:
    """Для комментариев в Bitrix: 'Иван Петров (@username, tg_id=123)'."""

    def _compose(full: str, username: str | None) -> str:
        u = f"@{username}" if username else "без username"
        return f"{full or 'без имени'} ({u}, tg_id={tg_id})"

    try:
        chat = await bot.get_chat(tg_id)
        first = (getattr(chat, "first_name", None) or "").strip()
        last = (getattr(chat, "last_name", None) or "").strip()
        username = getattr(chat, "username", None)
        full = (first + " " + last).strip()
        if full or username:
            return _compose(full, username)
    except Exception:
        pass

    try:
        async with async_session_maker() as session:
            user = await session.scalar(select(TGUser).where(TGUser.tg_id == tg_id))
        if user:
            full = ((user.tg_firstname or "") + " " + (user.tg_lastname or "")).strip()
            if full or user.tg_username:
                return _compose(full, user.tg_username)
    except Exception:
        pass

    return f"tg_id={tg_id}"


def _render_template(template: str, *, name: str) -> str:
    safe_name = (name or "").replace("{", "").replace("}", "").strip() or "друг"
    return template.format(name=safe_name)


# ============================================================
# комментарии в Bitrix
# ============================================================

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def _format_autoping_bitrix_comment(
    *, title: str, message_text: str, extra: str | None = None
) -> str:
    """В Bitrix сохраняем ровно тот текст, который ушёл клиенту (plain-text)."""
    clean = _strip_html(message_text).replace("\r\n", "\n").replace("\r", "\n").strip()

    parts = [title, "", "— Текст авто-сообщения —", clean or "<пусто>"]
    if extra:
        parts += ["", extra.strip()]

    return truncate_for_bitrix("\n".join(parts))


# ============================================================
# состояние (старт / активность)
# ============================================================


async def mark_start(tg_id: int, deal_id: str | None) -> None:
    now = datetime.utcnow()
    async with async_session_maker() as session:
        row = await session.get(AutoFollowupState, tg_id)
        if not row:
            row = AutoFollowupState(tg_id=tg_id)
            session.add(row)

        row.started_at = row.started_at or now
        row.deal_id = deal_id or row.deal_id
        await session.commit()


async def mark_activity(tg_id: int) -> None:
    now = datetime.utcnow()
    async with async_session_maker() as session:
        row = await session.get(AutoFollowupState, tg_id)
        if not row:
            row = AutoFollowupState(tg_id=tg_id)
            session.add(row)

        row.last_activity_at = now
        await session.commit()


# ============================================================
# атомарные «заявки» на отправку (защита от дублей)
# ============================================================


async def _claim(tg_id: int, column) -> Optional[datetime]:
    claimed_at = datetime.utcnow()
    async with async_session_maker() as session:
        res = await session.execute(
            update(AutoFollowupState)
            .where(and_(AutoFollowupState.tg_id == tg_id, column.is_(None)))
            .values({column: claimed_at})
        )
        await session.commit()
        return claimed_at if (res.rowcount or 0) == 1 else None


async def _release(tg_id: int, column, claimed_at: datetime) -> None:
    async with async_session_maker() as session:
        await session.execute(
            update(AutoFollowupState)
            .where(and_(AutoFollowupState.tg_id == tg_id, column == claimed_at))
            .values({column: None})
        )
        await session.commit()


async def claim_first_send(tg_id: int) -> Optional[datetime]:
    return await _claim(tg_id, AutoFollowupState.first_sent_at)


async def claim_second_send(tg_id: int) -> Optional[datetime]:
    return await _claim(tg_id, AutoFollowupState.second_sent_at)


async def release_first_send(tg_id: int, claimed_at: datetime) -> None:
    await _release(tg_id, AutoFollowupState.first_sent_at, claimed_at)


async def release_second_send(tg_id: int, claimed_at: datetime) -> None:
    await _release(tg_id, AutoFollowupState.second_sent_at, claimed_at)


# ============================================================
# примитивы Telegram / Bitrix
# ============================================================


async def _send_text(bot: Bot, tg_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=tg_id, text=text, disable_web_page_preview=True)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await bot.send_message(chat_id=tg_id, text=text, disable_web_page_preview=True)


async def _comment_and_move(
    deal_id: str,
    category_id: int | None,
    *,
    status_id: str,
    comment: str,
) -> None:
    try:
        await bitrix.add_deal_timeline_comment(deal_id, comment)
    except Exception:
        logger.warning("Не удалось записать комментарий в сделку %s", deal_id)

    try:
        await bitrix.set_deal_stage(
            deal_id=deal_id, stage_id=build_stage_id(category_id, status_id)
        )
    except Exception:
        logger.warning("Не удалось сменить стадию сделки %s", deal_id)


async def _list_all_deals_by_status(status_id: str) -> List[Dict[str, Any]]:
    """Сделки в указанной стадии по всем воронкам."""
    try:
        cats = await bitrix.list_categories()
    except Exception:
        logger.warning("Не удалось получить список воронок")
        cats = [{"ID": 0, "NAME": "base"}]

    out: List[Dict[str, Any]] = []
    for c in cats:
        cid = int(c.get("ID", 0))
        try:
            deals = await bitrix.list_deals_for_broadcast(
                category_id=cid, stage_id=build_stage_id(cid, status_id)
            )
        except Exception:
            logger.warning("Не удалось получить сделки воронки %s", cid)
            continue
        out.extend(deals)
    return out


def _deal_tg_id(deal: Dict[str, Any]) -> Optional[int]:
    raw = deal.get(BITRIX_FIELD_TG_ID_DEAL)
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _get_state(tg_id: int) -> Optional[AutoFollowupState]:
    async with async_session_maker() as session:
        return await session.get(AutoFollowupState, tg_id)


async def _remember_deal_id(tg_id: int, deal_id: str) -> None:
    try:
        async with async_session_maker() as session:
            row = await session.get(AutoFollowupState, tg_id)
            if row:
                row.deal_id = deal_id
                await session.commit()
    except Exception:
        logger.warning("Не удалось сохранить deal_id для tg_id=%s", tg_id)


async def _send_autoping(
    bot: Bot,
    *,
    tg_id: int,
    deal_id: str,
    category_id: int | None,
    text: str,
    ordinal: int,
    release,
    claimed_at: datetime,
) -> bool:
    """
    Отправляет авто-сообщение. Возвращает True, если доставлено.
    Недоставку фиксируем в Bitrix и уводим сделку в ревизию.
    """
    try:
        await _send_text(bot, tg_id, text)
        return True
    except TelegramForbiddenError:
        await _comment_and_move(
            deal_id,
            category_id,
            status_id=STATUS_REVISION,
            comment=(
                f"❗ Авто-сообщение #{ordinal} не доставлено (blocked/forbidden). "
                "Переведено в ревизию."
            ),
        )
    except TelegramBadRequest as e:
        await _comment_and_move(
            deal_id,
            category_id,
            status_id=STATUS_REVISION,
            comment=(
                f"❗ Авто-сообщение #{ordinal} не доставлено (bad request: {e}). "
                "Переведено в ревизию."
            ),
        )
    except Exception as e:
        # Временная ошибка — снимаем «заявку», чтобы повторить на следующем круге.
        logger.warning("autoping%s send failed tg_id=%s: %r", ordinal, tg_id, e)
        try:
            await release(tg_id, claimed_at)
        except Exception:
            logger.warning("Не удалось освободить claim для tg_id=%s", tg_id)

    return False


# ============================================================
# воркеры
# ============================================================


async def _process_first_ping(bot: Bot, deal: Dict[str, Any]) -> None:
    tg_id = _deal_tg_id(deal)
    if tg_id is None:
        return

    stage_id = str(deal.get("STAGE_ID") or "")
    if status_from_stage_id(stage_id) != STATUS_INCOMING:
        return

    row = await _get_state(tg_id)
    if not row or not row.started_at:
        return
    if row.last_activity_at or row.first_sent_at:
        return
    if datetime.utcnow() - row.started_at < FIRST_PING_AFTER:
        return

    claimed_at = await claim_first_send(tg_id)
    if not claimed_at:
        return

    deal_id = str(deal.get("ID"))
    category_id = deal.get("CATEGORY_ID")

    msg1 = _render_template(MSG1_TEMPLATE, name=await _get_client_name(bot, tg_id))

    delivered = await _send_autoping(
        bot,
        tg_id=tg_id,
        deal_id=deal_id,
        category_id=category_id,
        text=msg1,
        ordinal=1,
        release=release_first_send,
        claimed_at=claimed_at,
    )
    if not delivered:
        return

    await _remember_deal_id(tg_id, deal_id)

    await _comment_and_move(
        deal_id,
        category_id,
        status_id=STATUS_AFTER_FIRST_PING,
        comment=_format_autoping_bitrix_comment(
            title="✅ Авто-сообщение #1 отправлено (нет активности после /start).",
            message_text=msg1,
            extra=(
                f"Клиент: {await _get_tg_client_identity(bot, tg_id)}\n"
                f"Stage => {STATUS_AFTER_FIRST_PING}"
            ),
        ),
    )


async def _process_second_ping(bot: Bot, deal: Dict[str, Any]) -> None:
    tg_id = _deal_tg_id(deal)
    if tg_id is None:
        return

    row = await _get_state(tg_id)
    if not row or not row.first_sent_at or row.second_sent_at:
        return
    if row.last_activity_at and row.last_activity_at > row.first_sent_at:
        return
    if datetime.utcnow() - row.first_sent_at < SECOND_PING_AFTER:
        return

    claimed_at = await claim_second_send(tg_id)
    if not claimed_at:
        return

    deal_id = str(deal.get("ID"))
    category_id = deal.get("CATEGORY_ID")

    msg2 = _render_template(MSG2_TEMPLATE, name=await _get_client_name(bot, tg_id))

    delivered = await _send_autoping(
        bot,
        tg_id=tg_id,
        deal_id=deal_id,
        category_id=category_id,
        text=msg2,
        ordinal=2,
        release=release_second_send,
        claimed_at=claimed_at,
    )
    if not delivered:
        return

    try:
        await bitrix.add_deal_timeline_comment(
            deal_id,
            _format_autoping_bitrix_comment(
                title="✅ Авто-сообщение #2 отправлено (нет ответа сутки после авто #1).",
                message_text=msg2,
                extra=f"Клиент: {await _get_tg_client_identity(bot, tg_id)}",
            ),
        )
    except Exception:
        logger.warning("Не удалось записать комментарий об авто #2 в сделку %s", deal_id)


async def _process_autolose(deal: Dict[str, Any]) -> None:
    tg_id = _deal_tg_id(deal)
    if tg_id is None:
        return

    row = await _get_state(tg_id)
    if not row or not row.second_sent_at:
        return
    if row.last_activity_at and row.last_activity_at > row.second_sent_at:
        return
    if datetime.utcnow() - row.second_sent_at < LOSE_AFTER:
        return

    await _comment_and_move(
        str(deal.get("ID")),
        deal.get("CATEGORY_ID"),
        status_id=STATUS_REVISION,
        comment="⛔ Нет ответа сутки после авто-сообщения #2. Переведено в ревизию.",
    )


async def worker_first_ping(bot: Bot) -> None:
    """Раз в час: сделки во входящей стадии, где клиент молчит больше часа."""
    while True:
        try:
            for deal in await _list_all_deals_by_status(STATUS_INCOMING):
                try:
                    await _process_first_ping(bot, deal)
                except Exception:
                    logger.exception("Ошибка обработки авто #1 для сделки %s", deal.get("ID"))
        except Exception:
            logger.exception("worker_first_ping: цикл упал, продолжаем")

        await asyncio.sleep(FIRST_PING_INTERVAL_SECONDS)


async def worker_followup_after_first(bot: Bot) -> None:
    """
    Раз в два часа проходим стадию «ждём ответ» один раз и для каждой сделки
    решаем: пора отправить авто #2 или пора уводить в ревизию.
    """
    while True:
        try:
            for deal in await _list_all_deals_by_status(STATUS_AFTER_FIRST_PING):
                if status_from_stage_id(str(deal.get("STAGE_ID") or "")) != STATUS_AFTER_FIRST_PING:
                    continue
                try:
                    await _process_second_ping(bot, deal)
                    await _process_autolose(deal)
                except Exception:
                    logger.exception("Ошибка обработки follow-up для сделки %s", deal.get("ID"))
        except Exception:
            logger.exception("worker_followup_after_first: цикл упал, продолжаем")

        await asyncio.sleep(FOLLOWUP_INTERVAL_SECONDS)
