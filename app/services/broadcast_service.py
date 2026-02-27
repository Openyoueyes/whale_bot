# app/services/broadcast_service.py

from __future__ import annotations

import asyncio
from enum import Enum
from typing import Optional, Set, Dict, Iterable, Literal

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter, TelegramBadRequest
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.integrations.bitrix.client import BitrixClient
from app.config import BITRIX_FIELD_TG_ID_DEAL

bitrix_client = BitrixClient()

BLOCKED_STAGE_ID = "UC_HAYQ51"  # куда переносим, если пользователь заблокировал бота


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
    """
    В Bitrix сделки обычно требуют префикс категории: C{CATEGORY_ID}:{STAGE}
    Если stage_id уже с префиксом — вернём как есть.
    """
    if ":" in stage_id:
        return stage_id

    cat_raw = deal.get("CATEGORY_ID")
    try:
        cat_id = int(cat_raw) if cat_raw is not None else 0
    except (TypeError, ValueError):
        cat_id = 0

    return f"C{cat_id}:{stage_id}" if cat_id else stage_id


async def _move_deal_to_blocked_stage(tg_id: int) -> None:
    """
    Переводит сделку пользователя в стадию BLOCKED_STAGE_ID.
    """
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

    # 1) переносим стадию
    try:
        await bitrix_client.set_deal_stage(deal_id, target_stage)
    except Exception:
        return

    # 2) комментарий (не критично)
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

def _quiz_start_kb(text: str = "🎯 Пройти тест") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data="quiz:start")]
        ]
    )


async def _apply_quiz_button_mode(
    bot: Bot,
    *,
    chat_id: int,
    copied_message_id: int,
    mode: QuizButtonMode,
    quiz_button_text: str,
) -> None:
    """
    mode:
      - None: ничего не делаем (оставляем как в оригинале)
      - "add": ставим клавиатуру с кнопкой квиза (заменяем любую существующую)
      - "remove": убираем любую inline-клавиатуру
    """
    if mode is None:
        return

    if mode == "remove":
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=copied_message_id,
            reply_markup=None,
        )
        return

    if mode == "add":
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=copied_message_id,
            reply_markup=_quiz_start_kb(text=quiz_button_text),
        )
        return


# =========================
# main sender
# =========================

async def send_message_broadcast(
    bot: Bot,
    recipients: Iterable[int],
    *,
    from_chat_id: int,
    message_id: int,

    # None | "add" | "remove"
    quiz_button_mode: QuizButtonMode = None,
    quiz_button_text: str = "🎯 Пройти тест",

    # ✅ то, что реально рассылалось (текст/caption + вложения), формируй в admin router
    bitrix_message_body: str | None = None,
) -> Dict[str, int]:
    """
    Универсальная рассылка:
      - копируем сообщение как есть (любой тип)
      - опционально: добавляем/удаляем inline-кнопку квиза
      - в Bitrix сохраняем именно содержимое (bitrix_message_body), а не "тип сообщения"

    quiz_button_mode:
      - None     -> оставить как в исходнике (ничего не меняем)
      - "add"    -> поставить кнопку квиза всем (заменит текущую inline-клавиатуру)
      - "remove" -> убрать inline-клавиатуру у всех
    """
    sent = 0
    failed = 0

    kb_mode_text = "keep"
    if quiz_button_mode == "add":
        kb_mode_text = "add"
    elif quiz_button_mode == "remove":
        kb_mode_text = "remove"

    body_for_bitrix = _truncate(bitrix_message_body or "<без текста>")

    for tg_id in recipients:
        delivered = False
        copied_id: Optional[int] = None

        # --- Telegram: copy_message ---
        try:
            copied = await bot.copy_message(chat_id=tg_id, from_chat_id=from_chat_id, message_id=message_id)
            copied_id = int(getattr(copied, "message_id", 0) or 0)
            delivered = True

        except TelegramForbiddenError:
            # пользователь заблокировал бота / бот не может писать
            failed += 1
            await _move_deal_to_blocked_stage(tg_id)
            continue

        except TelegramBadRequest as e:
            # иногда "chat not found" / "USER_DEACTIVATED" тоже сюда попадает
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

        # --- опционально правим inline-клавиатуру ---
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
                # если сообщение нельзя редактировать — игнорируем
                pass
            except Exception:
                pass

        if delivered:
            sent += 1

        # --- Bitrix: сохраняем именно то сообщение, которое рассылалось ---
        try:
            deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
        except Exception:
            deal = None

        if deal:
            deal_id = deal.get("ID")
            if deal_id:
                comment = (
                    "📢 Групповая рассылка из Telegram бота\n\n"
                    f"Кнопка квиза: {kb_mode_text}\n"
                    "-----------------------------\n"
                    "Текст/содержимое рассылки:\n\n"
                    f"{body_for_bitrix}"
                )
                try:
                    await bitrix_client.add_deal_timeline_comment(deal_id, comment)
                except Exception:
                    pass

    return {"sent": sent, "failed": failed}