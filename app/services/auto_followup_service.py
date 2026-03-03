# app/services/auto_followup_service.py
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional
import re

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest

from sqlalchemy import update, and_, select

from app.db.session import async_session_maker
from app.db.models import AutoFollowupState, TGUser
from app.integrations.bitrix.client import BitrixClient
from app.config import BITRIX_FIELD_TG_ID_DEAL

logger = logging.getLogger(__name__)
bitrix = BitrixClient()

# -------------------- Bitrix status_id (короткие) --------------------
STAGE_INCOMING = "NEW"   # входящая заявка
STAGE_AFTER_1 = "UC_F3ZLGB"    # после авто #1 / в ожидании ответа
STAGE_APOLOGY = "UC_6OBDV3"      # пользователь недоступен (blocked/deactivated/etc)
STAGE_REVISION = "UC_OMS9IC"   # отказ / недоставка / ревизия

# -------------------- Тексты авто-сообщений (ШАБЛОНЫ) --------------------
# ВАЖНО: добавили {name} — будет подставляться имя из Telegram
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
    "Или свяжитесь со мной напрямую @WhaleTradeSupport"
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
# helpers: stage id parsing/building
# ============================================================

def _status_from_stage_id(stage_id: str | None) -> str:
    """
    Bitrix может вернуть:
    - 'UC_OERKGY' (основная)
    - 'C5:UC_OERKGY' (категория 5)
    Нам нужно короткое: 'UC_OERKGY'
    """
    s = (stage_id or "").strip()
    if ":" in s:
        return s.split(":", 1)[1]
    return s


def _build_stage_id(category_id: int | None, status_id: str) -> str:
    try:
        cid = int(category_id or 0)
    except Exception:
        cid = 0
    return f"C{cid}:{status_id}" if cid > 0 else status_id


# ============================================================
# name / identity (Telegram + fallback DB)
# ============================================================

async def _get_client_name(bot: Bot, tg_id: int) -> str:
    """
    Для приветствия в Telegram-сообщении.
    Берём first_name из Telegram; если недоступно — из БД; иначе 'друг'.
    """
    # Telegram first
    try:
        chat = await bot.get_chat(tg_id)
        first = (getattr(chat, "first_name", None) or "").strip()
        if first:
            return first
    except Exception:
        pass

    # DB fallback
    try:
        async with async_session_maker() as session:
            user = await session.scalar(select(TGUser).where(TGUser.tg_id == tg_id))
        if user and user.tg_firstname:
            first = (user.tg_firstname or "").strip()
            if first:
                return first
    except Exception:
        pass

    return "друг"


async def _get_tg_client_identity(bot: Bot, tg_id: int) -> str:
    """
    Для комментариев в Bitrix.
    Возвращает строку вида:
      'Иван Петров (@username, tg_id=123)'
    """
    try:
        chat = await bot.get_chat(tg_id)
        username = getattr(chat, "username", None)
        first = (getattr(chat, "first_name", None) or "").strip()
        last = (getattr(chat, "last_name", None) or "").strip()
        full = (first + " " + last).strip()
        if full or username:
            u = f"@{username}" if username else "без username"
            name = full if full else "без имени"
            return f"{name} ({u}, tg_id={tg_id})"
    except Exception:
        pass

    try:
        async with async_session_maker() as session:
            user = await session.scalar(select(TGUser).where(TGUser.tg_id == tg_id))
        if user:
            full = ((user.tg_firstname or "") + " " + (user.tg_lastname or "")).strip()
            username = user.tg_username
            if full or username:
                u = f"@{username}" if username else "без username"
                name = full if full else "без имени"
                return f"{name} ({u}, tg_id={tg_id})"
    except Exception:
        pass

    return f"tg_id={tg_id}"


def _render_template(template: str, *, name: str) -> str:
    # Защита от фигурных скобок в имени и т.п.
    safe_name = (name or "").replace("{", "").replace("}", "").strip() or "друг"
    return template.format(name=safe_name)


# ============================================================
# Bitrix comment formatting (store real sent text)
# ============================================================

_BITRIX_COMMENT_MAX = 3500  # безопасный лимит

def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def _truncate(text: str, limit: int = _BITRIX_COMMENT_MAX) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 50].rstrip() + "\n...\n[обрезано]"


def _format_autoping_bitrix_comment(*, title: str, message_text: str, extra: str | None = None) -> str:
    """
    Сохраняем в Bitrix реальный текст, который был отправлен клиенту.
    Пишем plain-text (без HTML).
    """
    clean = _strip_html(message_text)
    clean = clean.replace("\r\n", "\n").replace("\r", "\n").strip()

    parts = [
        title,
        "",
        "— Текст авто-сообщения —",
        clean or "<пусто>",
    ]
    if extra:
        parts += ["", extra.strip()]

    return _truncate("\n".join(parts))


# ============================================================
# state markers (start/activity)
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
# idempotency claims (atomic)
# ============================================================

async def claim_first_send(tg_id: int) -> Optional[datetime]:
    claimed_at = datetime.utcnow()
    async with async_session_maker() as session:
        res = await session.execute(
            update(AutoFollowupState)
            .where(
                and_(
                    AutoFollowupState.tg_id == tg_id,
                    AutoFollowupState.first_sent_at.is_(None),
                )
            )
            .values(first_sent_at=claimed_at)
        )
        await session.commit()
        return claimed_at if (res.rowcount or 0) == 1 else None


async def claim_second_send(tg_id: int) -> Optional[datetime]:
    claimed_at = datetime.utcnow()
    async with async_session_maker() as session:
        res = await session.execute(
            update(AutoFollowupState)
            .where(
                and_(
                    AutoFollowupState.tg_id == tg_id,
                    AutoFollowupState.second_sent_at.is_(None),
                )
            )
            .values(second_sent_at=claimed_at)
        )
        await session.commit()
        return claimed_at if (res.rowcount or 0) == 1 else None


async def release_first_send(tg_id: int, claimed_at: datetime) -> None:
    async with async_session_maker() as session:
        await session.execute(
            update(AutoFollowupState)
            .where(
                and_(
                    AutoFollowupState.tg_id == tg_id,
                    AutoFollowupState.first_sent_at == claimed_at,
                )
            )
            .values(first_sent_at=None)
        )
        await session.commit()


async def release_second_send(tg_id: int, claimed_at: datetime) -> None:
    async with async_session_maker() as session:
        await session.execute(
            update(AutoFollowupState)
            .where(
                and_(
                    AutoFollowupState.tg_id == tg_id,
                    AutoFollowupState.second_sent_at == claimed_at,
                )
            )
            .values(second_sent_at=None)
        )
        await session.commit()


# ============================================================
# telegram / bitrix primitives
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
        pass

    try:
        await bitrix.set_deal_stage(deal_id=deal_id, stage_id=_build_stage_id(category_id, status_id))
    except Exception:
        pass


async def _comment_only(deal_id: str, comment: str) -> None:
    try:
        await bitrix.add_deal_timeline_comment(deal_id, comment)
    except Exception:
        pass


async def _list_all_deals_by_status(status_id: str) -> list[dict]:
    try:
        cats = await bitrix.list_categories()
    except Exception:
        cats = [{"ID": 0, "NAME": "base"}]

    out: list[dict] = []
    for c in cats:
        cid = int(c.get("ID", 0))
        stage_full = _build_stage_id(cid, status_id)
        try:
            deals = await bitrix.list_deals_for_broadcast(category_id=cid, stage_id=stage_full)
        except Exception:
            deals = []
        out.extend(deals)
    return out


# ============================================================
# workers
# ============================================================

async def worker_autoping_1(bot: Bot) -> None:
    """
    Каждые 1 час:
    - сделки в UC_OERKGY
    - если был /start и нет активности -> MSG1 -> stage => UC_R1NGXP
    """
    while True:
        try:
            deals = await _list_all_deals_by_status(STAGE_INCOMING)
        except Exception:
            deals = []

        for d in deals:
            tg_raw = d.get(BITRIX_FIELD_TG_ID_DEAL)
            if not tg_raw:
                continue
            try:
                tg_id = int(tg_raw)
            except Exception:
                continue

            deal_id = str(d.get("ID"))
            category_id = d.get("CATEGORY_ID")
            stage_id = str(d.get("STAGE_ID") or "")

            if _status_from_stage_id(stage_id) != STAGE_INCOMING:
                continue

            now = datetime.utcnow()

            async with async_session_maker() as session:
                row = await session.get(AutoFollowupState, tg_id)
                if not row or not row.started_at:
                    continue
                if row.last_activity_at:
                    continue
                if row.first_sent_at:
                    continue
                if now - row.started_at < timedelta(hours=1):
                    continue

            claimed_at = await claim_first_send(tg_id)
            if not claimed_at:
                continue

            # --- персонализация ---
            name = await _get_client_name(bot, tg_id)
            msg1 = _render_template(MSG1_TEMPLATE, name=name)

            # отправка
            try:
                await _send_text(bot, tg_id, msg1)
            except TelegramForbiddenError:
                await _comment_and_move(
                    deal_id,
                    category_id,
                    status_id=STAGE_REVISION,
                    comment="❗ Авто-сообщение #1 не доставлено (blocked/forbidden). Переведено в STAGE_REVISION.",
                )
                continue
            except TelegramBadRequest as e:
                await _comment_and_move(
                    deal_id,
                    category_id,
                    status_id=STAGE_REVISION,
                    comment=f"❗ Авто-сообщение #1 не доставлено (bad request: {e}). Переведено в STAGE_REVISION.",
                )
                continue
            except Exception as e:
                logger.warning("autoping1 send failed tg_id=%s: %r", tg_id, e)
                try:
                    await release_first_send(tg_id, claimed_at)
                except Exception:
                    pass
                continue

            # подстрахуем deal_id в state (не критично)
            try:
                async with async_session_maker() as session:
                    row = await session.get(AutoFollowupState, tg_id)
                    if row:
                        row.deal_id = deal_id
                        await session.commit()
            except Exception:
                pass

            client_identity = await _get_tg_client_identity(bot, tg_id)

            await _comment_and_move(
                deal_id,
                category_id,
                status_id=STAGE_AFTER_1,
                comment=_format_autoping_bitrix_comment(
                    title="✅ Авто-сообщение #1 отправлено (нет активности после /start).",
                    message_text=msg1,  # сохраняем РЕАЛЬНО отправленный текст
                    extra=(
                        f"Клиент: {client_identity}\n"
                        f"Stage => {STAGE_AFTER_1}"
                    ),
                ),
            )

        await asyncio.sleep(3600)


async def worker_autoping_2(bot: Bot) -> None:
    """
    Каждые 2 часа:
    - сделки в UC_R1NGXP
    - если сутки нет ответа после авто #1 -> MSG2 -> comment (стадию не меняем)
    """
    while True:
        try:
            deals = await _list_all_deals_by_status(STAGE_AFTER_1)
        except Exception:
            deals = []

        for d in deals:
            tg_raw = d.get(BITRIX_FIELD_TG_ID_DEAL)
            if not tg_raw:
                continue
            try:
                tg_id = int(tg_raw)
            except Exception:
                continue

            deal_id = str(d.get("ID"))
            category_id = d.get("CATEGORY_ID")
            stage_id = str(d.get("STAGE_ID") or "")

            if _status_from_stage_id(stage_id) != STAGE_AFTER_1:
                continue

            now = datetime.utcnow()

            async with async_session_maker() as session:
                row = await session.get(AutoFollowupState, tg_id)
                if not row or not row.first_sent_at:
                    continue
                if row.second_sent_at:
                    continue
                if row.last_activity_at and row.last_activity_at > row.first_sent_at:
                    continue
                if now - row.first_sent_at < timedelta(hours=24):
                    continue

            claimed_at = await claim_second_send(tg_id)
            if not claimed_at:
                continue

            # --- персонализация ---
            name = await _get_client_name(bot, tg_id)
            msg2 = _render_template(MSG2_TEMPLATE, name=name)

            try:
                await _send_text(bot, tg_id, msg2)
            except TelegramForbiddenError:
                await _comment_and_move(
                    deal_id,
                    category_id,
                    status_id=STAGE_REVISION,
                    comment="❗ Авто-сообщение #2 не доставлено (blocked/forbidden). Переведено в STAGE_REVISION.",
                )
                continue
            except TelegramBadRequest as e:
                await _comment_and_move(
                    deal_id,
                    category_id,
                    status_id=STAGE_REVISION,
                    comment=f"❗ Авто-сообщение #2 не доставлено (bad request: {e}). Переведено в STAGE_REVISION.",
                )
                continue
            except Exception as e:
                logger.warning("autoping2 send failed tg_id=%s: %r", tg_id, e)
                try:
                    await release_second_send(tg_id, claimed_at)
                except Exception:
                    pass
                continue

            client_identity = await _get_tg_client_identity(bot, tg_id)

            await _comment_only(
                deal_id,
                _format_autoping_bitrix_comment(
                    title="✅ Авто-сообщение #2 отправлено (нет ответа сутки после авто #1).",
                    message_text=msg2,  # сохраняем РЕАЛЬНО отправленный текст
                    extra=f"Клиент: {client_identity}",
                ),
            )

        await asyncio.sleep(7200)


async def worker_autolose(bot: Bot) -> None:
    """
    Каждые 2 часа:
    - сделки в UC_R1NGXP
    - если сутки нет ответа после авто #2 -> STAGE_REVISION + comment
    """
    while True:
        try:
            deals = await _list_all_deals_by_status(STAGE_AFTER_1)
        except Exception:
            deals = []

        for d in deals:
            tg_raw = d.get(BITRIX_FIELD_TG_ID_DEAL)
            if not tg_raw:
                continue
            try:
                tg_id = int(tg_raw)
            except Exception:
                continue

            deal_id = str(d.get("ID"))
            category_id = d.get("CATEGORY_ID")
            stage_id = str(d.get("STAGE_ID") or "")

            if _status_from_stage_id(stage_id) != STAGE_AFTER_1:
                continue

            now = datetime.utcnow()

            async with async_session_maker() as session:
                row = await session.get(AutoFollowupState, tg_id)
                if not row or not row.second_sent_at:
                    continue
                if row.last_activity_at and row.last_activity_at > row.second_sent_at:
                    continue
                if now - row.second_sent_at < timedelta(hours=24):
                    continue

            await _comment_and_move(
                deal_id,
                category_id,
                status_id=STAGE_REVISION,
                comment="⛔ Нет ответа сутки после авто-сообщения #2. Переведено в STAGE_REVISION.",
            )

        await asyncio.sleep(7200)