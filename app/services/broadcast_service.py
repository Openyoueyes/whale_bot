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

_BITRIX_COMMENT_MAX = 3500
_NAME_FALLBACK = "трейдер"


def _truncate(text: str, limit: int = _BITRIX_COMMENT_MAX) -> str:
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    return t[: limit - 50].rstrip() + "\n...\n[обрезано]"


def _first_name_from_bitrix_name(name: str | None, *, fallback: str = _NAME_FALLBACK) -> str:
    s = (name or "").strip()
    if not s:
        return fallback
    s = re.sub(r"\s+", " ", s)
    first = s.split(" ", 1)[0].strip()
    return first or fallback


def _replace_name_placeholder(text: str, first_name: str) -> str:
    # ровно то, что ты хочешь: <name>
    return (text or "").replace("<name>", first_name)


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


def _quiz_start_kb(text: str = "🧠 Пройти проф-тест трейдера") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data="quiz:start")]])


async def _apply_quiz_button_mode(
    bot: Bot,
    *,
    chat_id: int,
    copied_message_id: int,
    mode: QuizButtonMode,
    quiz_button_text: str,
) -> None:
    if mode is None:
        return

    if mode == "remove":
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=copied_message_id, reply_markup=None)
        return

    if mode == "add":
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=copied_message_id,
            reply_markup=_quiz_start_kb(text=quiz_button_text),
        )
        return


async def _get_first_name_from_bitrix_by_tg_id(tg_id: int) -> str:
    """
    1) находим сделку по TG_ID
    2) из сделки берём CONTACT_ID (через crm.deal.get)
    3) crm.contact.get -> NAME -> первое слово
    """
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None

    if not deal:
        return _NAME_FALLBACK

    deal_id = deal.get("ID")
    if not deal_id:
        return _NAME_FALLBACK

    try:
        full_deal = await bitrix_client.get_deal(deal_id)
    except Exception:
        full_deal = {}

    # Bitrix обычно: CONTACT_ID (строка) либо CONTACT_IDS (массив)
    contact_id = full_deal.get("CONTACT_ID")
    if not contact_id:
        # иногда бывает массив
        ids = full_deal.get("CONTACT_IDS")
        if isinstance(ids, list) and ids:
            contact_id = ids[0].get("CONTACT_ID") or ids[0].get("ID")

    if not contact_id:
        return _NAME_FALLBACK

    try:
        contact = await bitrix_client.get_contact(contact_id)
    except Exception:
        contact = {}

    return _first_name_from_bitrix_name(contact.get("NAME"), fallback=_NAME_FALLBACK)


async def _personalize_copied_message(
    bot: Bot,
    *,
    chat_id: int,
    copied_message_id: int,
    template_text: str,
    first_name: str,
    original_reply_markup: InlineKeyboardMarkup | None,
) -> None:
    """
    Если исходник был:
      - текст → edit_message_text
      - медиа с caption → edit_message_caption
    Мы не знаем тип, поэтому пробуем text, если не получится — caption.
    IMPORTANT: чтобы не потерять кнопки при keep — переустанавливаем original_reply_markup.
    """
    personalized = _replace_name_placeholder(template_text, first_name)

    if personalized == template_text:
        return  # нечего менять

    # 1) пробуем как TEXT
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=copied_message_id,
            text=personalized,
            parse_mode="HTML",
            reply_markup=original_reply_markup,
            disable_web_page_preview=True,
        )
        return
    except TelegramBadRequest:
        pass
    except Exception:
        pass

    # 2) пробуем как CAPTION
    try:
        await bot.edit_message_caption(
            chat_id=chat_id,
            message_id=copied_message_id,
            caption=personalized,
            parse_mode="HTML",
            reply_markup=original_reply_markup,
        )
    except Exception:
        pass


async def send_message_broadcast(
    bot: Bot,
    recipients: Iterable[int],
    *,
    from_chat_id: int,
    message_id: int,

    quiz_button_mode: QuizButtonMode = None,
    quiz_button_text: str = "🧠 Пройти проф-тест трейдера",

    bitrix_message_body: str | None = None,

    # ✅ NEW: персонализация <name> для любого типа
    telegram_template_text: str = "",
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

    need_personalize = "<name>" in (telegram_template_text or "")

    # кеш имён, чтобы не дергать Bitrix 1000 раз
    name_cache: Dict[int, str] = {}

    for tg_id in recipients:
        delivered = False
        copied_id: Optional[int] = None

        # --- Telegram: copy_message ---
        try:
            copied = await bot.copy_message(chat_id=tg_id, from_chat_id=from_chat_id, message_id=message_id)
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

        # --- персонализация <name> (сначала), чтобы потом не ломать кнопки режима ---
        if delivered and copied_id and need_personalize:
            if tg_id not in name_cache:
                name_cache[tg_id] = await _get_first_name_from_bitrix_by_tg_id(tg_id)
            first_name = name_cache[tg_id]

            await _personalize_copied_message(
                bot,
                chat_id=tg_id,
                copied_message_id=copied_id,
                template_text=telegram_template_text,
                first_name=first_name,
                original_reply_markup=original_reply_markup,
            )

        # --- опционально правим inline-клавиатуру (quiz button mode) ---
        if delivered and copied_id:
            try:
                await _apply_quiz_button_mode(
                    bot,
                    chat_id=tg_id,
                    copied_message_id=copied_id,
                    mode=quiz_button_mode,
                    quiz_button_text=quiz_button_text,
                )
            except TelegramBadRequest:
                pass
            except Exception:
                pass

        if delivered:
            sent += 1

        # --- Bitrix comment (как у тебя было) ---
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