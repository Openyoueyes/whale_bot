# app/services/broadcast_service.py
"""
Групповая рассылка по сделкам из Bitrix.

Ключевая идея: список сделок уже загружен на этапе выбора получателей, поэтому
в цикле отправки мы НЕ ходим в Bitrix за той же сделкой заново. На получателя
остаётся максимум один запрос (комментарий в таймлайн) плюс контакт, если в
тексте есть подстановка {name}.
"""

from __future__ import annotations

import asyncio
import logging
import re
from enum import Enum
from typing import Any, Dict, Literal, Mapping, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import BITRIX_FIELD_TG_ID_DEAL, BROADCAST_DELAY_SECONDS
from app.integrations.bitrix.client import BitrixClient
from app.services.bitrix_stages import STATUS_UNAVAILABLE, stage_id_for_deal
from app.services.message_formatters import truncate_for_bitrix

logger = logging.getLogger(__name__)

bitrix_client = BitrixClient()


class BroadcastScope(str, Enum):
    ALL = "all"
    PIPELINE = "pipeline"
    STAGE = "stage"


QuizButtonMode = Optional[Literal["add", "remove"]]  # None = оставить как есть

# tg_id -> сделка Bitrix
Recipients = Dict[int, Dict[str, Any]]

# =========================
# получатели
# =========================


async def collect_recipients(
    scope: BroadcastScope,
    category_id: Optional[int] = None,
    stage_id: Optional[str] = None,
) -> Recipients:
    """
    Возвращает {tg_id: сделка}. Сделку сохраняем целиком, чтобы в цикле
    отправки не запрашивать её повторно.
    """
    if scope == BroadcastScope.ALL:
        deals = await bitrix_client.list_deals_for_broadcast()
    elif scope == BroadcastScope.PIPELINE:
        if category_id is None:
            return {}
        deals = await bitrix_client.list_deals_for_broadcast(category_id=category_id)
    elif scope == BroadcastScope.STAGE:
        if category_id is None or stage_id is None:
            return {}
        deals = await bitrix_client.list_deals_for_broadcast(
            category_id=category_id, stage_id=stage_id
        )
    else:
        return {}

    recipients: Recipients = {}
    for deal in deals:
        tg_id_raw = deal.get(BITRIX_FIELD_TG_ID_DEAL)
        if not tg_id_raw:
            continue
        try:
            recipients[int(tg_id_raw)] = deal
        except (TypeError, ValueError):
            continue

    return recipients


async def _move_deal_to_blocked_stage(deal: Dict[str, Any]) -> None:
    """Клиент заблокировал бота — уводим сделку в стадию недоставки."""
    deal_id = deal.get("ID")
    if not deal_id:
        return

    try:
        await bitrix_client.set_deal_stage(deal_id, stage_id_for_deal(deal, STATUS_UNAVAILABLE))
    except Exception:
        logger.warning("Не удалось перевести сделку %s в стадию недоставки", deal_id)
        return

    try:
        await bitrix_client.add_deal_timeline_comment(
            deal_id,
            "⛔️ Пользователь заблокировал бота — авто-перенос в стадию недоставки (broadcast).",
        )
    except Exception:
        logger.warning("Не удалось прокомментировать недоставку в сделке %s", deal_id)


# =========================
# кнопки
# =========================


def _quiz_start_kb(text: str = "🧠 Пройти проф-тест трейдера") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=text, callback_data="quiz:start")]]
    )


def _compute_target_reply_markup(
    *,
    mode: QuizButtonMode,
    quiz_button_text: str,
    original_reply_markup: InlineKeyboardMarkup | None,
) -> InlineKeyboardMarkup | None:
    """
    Какая клавиатура должна остаться у скопированного сообщения:
      None (keep) — оригинальная, remove — никакой, add — кнопка теста.
    """
    if mode == "remove":
        return None
    if mode == "add":
        return _quiz_start_kb(text=quiz_button_text)
    return original_reply_markup


# =========================
# персонализация
# =========================


async def _first_name_from_deal(deal: Dict[str, Any]) -> Optional[str]:
    """
    Имя берём из контакта сделки: CONTACT_ID уже есть в загруженной сделке,
    поэтому нужен только crm.contact.get.
    """
    contact_id = deal.get("CONTACT_ID")

    if not contact_id:
        contact_ids = deal.get("CONTACT_IDS") or []
        if isinstance(contact_ids, list) and contact_ids:
            first = contact_ids[0]
            contact_id = first.get("CONTACT_ID") if isinstance(first, dict) else first

    if not contact_id:
        return None

    try:
        contact = await bitrix_client.get_contact(contact_id)
    except Exception:
        return None

    name_raw = (contact.get("NAME") or "").strip()
    if not name_raw:
        return None

    return re.split(r"\s+", name_raw)[0].strip() or None


def _personalize_html(html: str, name: str) -> str:
    return html.replace("{name}", name)


# =========================
# отправка
# =========================


async def send_message_broadcast(
    bot: Bot,
    recipients: Mapping[int, Dict[str, Any]],
    *,
    from_chat_id: int,
    message_id: int,
    quiz_button_mode: QuizButtonMode = None,
    quiz_button_text: str = "🧠 Пройти проф-тест трейдера",
    bitrix_message_body: str | None = None,
    tg_html_body: str | None = None,
    tg_html_kind: str | None = None,  # "text" | "caption" | None
    original_reply_markup: InlineKeyboardMarkup | None = None,
) -> Dict[str, int]:
    sent = 0
    failed = 0

    kb_mode_text = quiz_button_mode or "keep"
    body_for_bitrix = truncate_for_bitrix(bitrix_message_body or "<без текста>")

    target_markup = _compute_target_reply_markup(
        mode=quiz_button_mode,
        quiz_button_text=quiz_button_text,
        original_reply_markup=original_reply_markup,
    )

    needs_personalization = bool(tg_html_body and tg_html_kind and "{name}" in tg_html_body)

    comment = (
        "📢 Групповая рассылка из Telegram бота\n\n"
        f"Кнопка теста: {kb_mode_text}\n"
        "-----------------------------\n"
        "Текст/содержимое рассылки:\n\n"
        f"{body_for_bitrix}"
    )

    for tg_id, deal in recipients.items():
        copied_id = await _copy_to_recipient(
            bot,
            tg_id=tg_id,
            deal=deal,
            from_chat_id=from_chat_id,
            message_id=message_id,
            reply_markup=target_markup,
        )

        if copied_id is None:
            failed += 1
            continue

        sent += 1

        if needs_personalization and copied_id:
            await _personalize_delivered(
                bot,
                tg_id=tg_id,
                message_id=copied_id,
                deal=deal,
                tg_html_body=tg_html_body or "",
                tg_html_kind=tg_html_kind,
                target_markup=target_markup,
            )

        deal_id = deal.get("ID")
        if deal_id:
            try:
                await bitrix_client.add_deal_timeline_comment(deal_id, comment)
            except Exception:
                logger.warning("Не удалось записать рассылку в сделку %s", deal_id)

        if BROADCAST_DELAY_SECONDS > 0:
            await asyncio.sleep(BROADCAST_DELAY_SECONDS)

    return {"sent": sent, "failed": failed}


async def _copy_to_recipient(
    bot: Bot,
    *,
    tg_id: int,
    deal: Dict[str, Any],
    from_chat_id: int,
    message_id: int,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> Optional[int]:
    """
    Копирует сообщение получателю. Возвращает message_id копии или None.

    Клавиатуру передаём прямо в copyMessage: копия не наследует кнопки
    оригинала, а отдельный edit_message_reply_markup — лишний запрос к Telegram
    на каждого получателя.
    """
    for attempt in range(2):
        try:
            copied = await bot.copy_message(
                chat_id=tg_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
            return int(getattr(copied, "message_id", 0) or 0)

        except TelegramRetryAfter as e:
            if attempt == 0:
                await asyncio.sleep(e.retry_after)
                continue
            return None

        except TelegramForbiddenError:
            await _move_deal_to_blocked_stage(deal)
            return None

        except TelegramBadRequest as e:
            msg = (str(e) or "").lower()
            if "chat not found" in msg or "user is deactivated" in msg:
                await _move_deal_to_blocked_stage(deal)
            return None

        except Exception:
            logger.warning("Не удалось доставить рассылку tg_id=%s", tg_id)
            return None

    return None


async def _personalize_delivered(
    bot: Bot,
    *,
    tg_id: int,
    message_id: int,
    deal: Dict[str, Any],
    tg_html_body: str,
    tg_html_kind: str | None,
    target_markup: InlineKeyboardMarkup | None,
) -> None:
    """Подставляет {name} в уже доставленное сообщение, сохраняя форматирование."""
    first_name = await _first_name_from_deal(deal) or "трейдер"
    html_body = _personalize_html(tg_html_body, first_name)

    try:
        if tg_html_kind == "text":
            await bot.edit_message_text(
                chat_id=tg_id,
                message_id=message_id,
                text=html_body,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=target_markup,
            )
        elif tg_html_kind == "caption":
            await bot.edit_message_caption(
                chat_id=tg_id,
                message_id=message_id,
                caption=html_body,
                parse_mode="HTML",
                reply_markup=target_markup,
            )
    except Exception:
        logger.warning("Не удалось персонализировать рассылку для tg_id=%s", tg_id)
