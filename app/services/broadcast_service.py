from __future__ import annotations

import asyncio
import re
from enum import Enum
from typing import Optional, Set, Dict, Iterable, Literal

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.integrations.bitrix.client import BitrixClient
from app.config import BITRIX_FIELD_TG_ID_DEAL

bitrix_client = BitrixClient()

BLOCKED_STAGE_ID = "UC_6OBDV3"  # куда переносим, если пользователь заблокировал бота


class BroadcastScope(str, Enum):
    ALL = "all"
    PIPELINE = "pipeline"
    STAGE = "stage"


QuizButtonMode = Optional[Literal["add", "remove"]]  # None = keep as original


# =========================
# helpers
# =========================

_BITRIX_COMMENT_MAX = 3500


def _truncate(text: str, limit: int = _BITRIX_COMMENT_MAX) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 50].rstrip() + "\n...\n[обрезано]"


# =========================
# recipients
# =========================

async def collect_recipients(
    scope: BroadcastScope,
    category_id: Optional[int] = None,
    stage_id: Optional[str] = None,
) -> Set[int]:
    if scope == BroadcastScope.ALL:
        deals = await bitrix_client.list_deals_for_broadcast()
    elif scope == BroadcastScope.PIPELINE:
        if category_id is None:
            return set()
        deals = await bitrix_client.list_deals_for_broadcast(category_id=category_id)
    elif scope == BroadcastScope.STAGE:
        if category_id is None or stage_id is None:
            return set()
        deals = await bitrix_client.list_deals_for_broadcast(category_id=category_id, stage_id=stage_id)
    else:
        return set()

    recipients: Set[int] = set()
    for deal in deals:
        tg_id_raw = deal.get(BITRIX_FIELD_TG_ID_DEAL)
        if not tg_id_raw:
            continue
        try:
            recipients.add(int(tg_id_raw))
        except (TypeError, ValueError):
            continue

    return recipients


def _bitrix_stage_with_category(deal: dict, stage_id: str) -> str:
    if ":" in stage_id:
        return stage_id

    cat_raw = deal.get("CATEGORY_ID")
    try:
        cat_id = int(cat_raw) if cat_raw is not None else 0
    except (TypeError, ValueError):
        cat_id = 0

    return f"C{cat_id}:{stage_id}" if cat_id else stage_id


async def _move_deal_to_blocked_stage(tg_id: int) -> None:
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None

    if not deal:
        return

    deal_id = deal.get("ID")
    if not deal_id:
        return

    target_stage = _bitrix_stage_with_category(deal, BLOCKED_STAGE_ID)

    try:
        await bitrix_client.set_deal_stage(deal_id, target_stage)
    except Exception:
        return

    try:
        await bitrix_client.add_deal_timeline_comment(
            deal_id,
            "⛔️ Пользователь заблокировал бота — авто-перенос в стадию недоставки (broadcast).",
        )
    except Exception:
        pass


# =========================
# quiz button helpers
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
    Возвращает какую клавиатуру держать у СКОПИРОВАННОГО сообщения:
      - keep (mode None): оставляем оригинальную (из сообщения администратора)
      - remove: None
      - add: quiz_start_kb
    """
    if mode is None:
        return original_reply_markup
    if mode == "remove":
        return None
    if mode == "add":
        return _quiz_start_kb(text=quiz_button_text)
    return original_reply_markup


async def _apply_reply_markup(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    reply_markup: InlineKeyboardMarkup | None,
) -> None:
    await bot.edit_message_reply_markup(
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=reply_markup,
    )


# =========================
# Bitrix name helpers
# =========================

async def _get_first_name_from_bitrix(tg_id: int) -> str | None:
    """
    Имя берём из контакта Bitrix:
      deal by TG_ID -> CONTACT_ID -> contact.get -> NAME -> first word
    Если CONTACT_ID нет — вернём None.
    """
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None
    if not deal:
        return None

    deal_id = deal.get("ID")
    if not deal_id:
        return None

    try:
        full_deal = await bitrix_client.get_deal(deal_id)
    except Exception:
        return None

    contact_id = full_deal.get("CONTACT_ID")

    # fallback: CONTACT_IDS (если порталом возвращается список)
    if not contact_id:
        contact_ids = full_deal.get("CONTACT_IDS") or []
        if isinstance(contact_ids, list) and contact_ids:
            first = contact_ids[0]
            if isinstance(first, dict):
                contact_id = first.get("CONTACT_ID")
            else:
                contact_id = first

    if not contact_id:
        return None

    try:
        contact = await bitrix_client.get_contact(contact_id)
    except Exception:
        return None

    name_raw = (contact.get("NAME") or "").strip()
    if not name_raw:
        return None

    # NAME у тебя типа "Алексей Дмитриев" => берём "Алексей"
    first_name = re.split(r"\s+", name_raw)[0].strip()
    return first_name or None


def _personalize_html(html: str, name: str) -> str:
    return html.replace("{name}", name)


# =========================
# main sender
# =========================

async def send_message_broadcast(
    bot: Bot,
    recipients: Iterable[int],
    *,
    from_chat_id: int,
    message_id: int,

    quiz_button_mode: QuizButtonMode = None,
    quiz_button_text: str = "🧠 Пройти проф-тест трейдера",

    bitrix_message_body: str | None = None,

    # ✅ персонализация {name} с сохранением форматирования
    tg_html_body: str | None = None,
    tg_html_kind: str | None = None,  # "text" | "caption" | None
    original_reply_markup: InlineKeyboardMarkup | None = None,
) -> Dict[str, int]:
    sent = 0
    failed = 0

    kb_mode_text = "keep"
    if quiz_button_mode == "add":
        kb_mode_text = "add"
    elif quiz_button_mode == "remove":
        kb_mode_text = "remove"

    body_for_bitrix = _truncate(bitrix_message_body or "<без текста>")

    # заранее вычислим, какую клаву хотим иметь у доставленного сообщения
    target_markup = _compute_target_reply_markup(
        mode=quiz_button_mode,
        quiz_button_text=quiz_button_text,
        original_reply_markup=original_reply_markup,
    )

    needs_personalization = bool(tg_html_body and tg_html_kind and "{name}" in tg_html_body)

    for tg_id in recipients:
        delivered = False
        copied_id: Optional[int] = None

        # --- Telegram: copy_message ---
        try:
            copied = await bot.copy_message(
                chat_id=tg_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
            )
            copied_id = int(getattr(copied, "message_id", 0) or 0)
            delivered = True

        except TelegramForbiddenError:
            failed += 1
            await _move_deal_to_blocked_stage(tg_id)
            continue

        except TelegramBadRequest as e:
            failed += 1
            msg = (str(e) or "").lower()
            if "chat not found" in msg or "user is deactivated" in msg:
                await _move_deal_to_blocked_stage(tg_id)
            continue

        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                copied = await bot.copy_message(chat_id=tg_id, from_chat_id=from_chat_id, message_id=message_id)
                copied_id = int(getattr(copied, "message_id", 0) or 0)
                delivered = True
            except TelegramForbiddenError:
                failed += 1
                await _move_deal_to_blocked_stage(tg_id)
                continue
            except Exception:
                failed += 1
                continue

        except Exception:
            failed += 1
            continue

        # --- 1) применяем/сохраняем клавиатуру (чтобы edit_text/caption потом её не "съел") ---
        if delivered and copied_id:
            try:
                # mode=None -> ставим original_reply_markup (если была)
                # mode=add/remove -> ставим целевую
                await _apply_reply_markup(
                    bot,
                    chat_id=tg_id,
                    message_id=copied_id,
                    reply_markup=target_markup,
                )
            except TelegramBadRequest:
                pass
            except Exception:
                pass

        # --- 2) персонализация {name} (HTML) ---
        if delivered and copied_id and needs_personalization:
            try:
                first_name = await _get_first_name_from_bitrix(tg_id)
                if not first_name:
                    first_name = "трейдер"

                html_body = _personalize_html(tg_html_body or "", first_name)

                # ВАЖНО: передаём reply_markup=target_markup, чтобы не слетали кнопки
                if tg_html_kind == "text":
                    await bot.edit_message_text(
                        chat_id=tg_id,
                        message_id=copied_id,
                        text=html_body,
                        parse_mode="HTML",
                        disable_web_page_preview=True,
                        reply_markup=target_markup,
                    )
                elif tg_html_kind == "caption":
                    await bot.edit_message_caption(
                        chat_id=tg_id,
                        message_id=copied_id,
                        caption=html_body,
                        parse_mode="HTML",
                        reply_markup=target_markup,
                    )
            except TelegramBadRequest:
                pass
            except Exception:
                pass

        if delivered:
            sent += 1

        # --- Bitrix: логируем текст рассылки ---
        try:
            deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
        except Exception:
            deal = None

        if deal:
            deal_id = deal.get("ID")
            if deal_id:
                comment = (
                    "📢 Групповая рассылка из Telegram бота\n\n"
                    f"Кнопка теста: {kb_mode_text}\n"
                    "-----------------------------\n"
                    "Текст/содержимое рассылки:\n\n"
                    f"{body_for_bitrix}"
                )
                try:
                    await bitrix_client.add_deal_timeline_comment(deal_id, comment)
                except Exception:
                    pass

    return {"sent": sent, "failed": failed}