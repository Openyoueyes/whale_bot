# app/bot/routers/business/dialog.py

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from aiogram import Router
from aiogram.types import Message, BusinessConnection

from app.services.bitrix_stage_guard import move_to_first_touch_if_needed
from app.services.business_service import ensure_deal_id_for_private_chat
from app.integrations.bitrix.client import BitrixClient
from app.config import GROUP_CHAT_MESSAGES_BOT_ID, GROUP__B_CHAT_MESSAGES_BOT_ID

logger = logging.getLogger(__name__)

router = Router(name="business-dialog")
bitrix = BitrixClient()

# ======== CACHE business connection status ========
# bc_id -> { manager_user_id: int, is_enabled: bool, can_reply: bool }
_BC_CACHE: Dict[str, Dict[str, Any]] = {}


def _is_private_chat(message: Message) -> bool:
    return bool(message.chat and message.chat.type == "private")


async def _notify_group(bot, text: str) -> None:
    if not GROUP_CHAT_MESSAGES_BOT_ID:
        return
    try:
        await bot.send_message(
            chat_id=GROUP_CHAT_MESSAGES_BOT_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        pass


async def _notify_b_group(bot, text: str) -> None:
    if not GROUP__B_CHAT_MESSAGES_BOT_ID:
        return
    try:
        await bot.send_message(
            chat_id=GROUP__B_CHAT_MESSAGES_BOT_ID,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        pass


async def _upsert_bc(bc: BusinessConnection) -> None:
    rights = getattr(bc, "rights", None)
    can_reply = getattr(rights, "can_reply", None) if rights else None

    _BC_CACHE[bc.id] = {
        "manager_user_id": bc.user.id,
        "is_enabled": bool(bc.is_enabled),
        "can_reply": True if can_reply is None else bool(can_reply),
    }


async def _ensure_bc_cached(bot, bc_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    После рестарта кэша нет — подтягиваем состояние business_connection один раз.
    """
    if not bc_id:
        return None

    if bc_id in _BC_CACHE:
        return _BC_CACHE[bc_id]

    try:
        bc_fresh = await bot.get_business_connection(business_connection_id=bc_id)
        await _upsert_bc(bc_fresh)
        return _BC_CACHE.get(bc_id)
    except Exception as e:
        logger.exception("get_business_connection failed (bc_id=%s): %s", bc_id, e)
        return None


def _format_message_for_bitrix(message: Message) -> str:
    text = message.html_text or message.text or message.caption or ""
    parts = []
    if text:
        parts.append(text)

    # фиксируем вложения (минимально, как у вас)
    if message.photo:
        parts.append(f"[photo] file_id={message.photo[-1].file_id}")
    if message.video:
        parts.append(f"[video] file_id={message.video.file_id}")
    if message.document:
        parts.append(f"[document] {message.document.file_name or ''} file_id={message.document.file_id}")
    if message.voice:
        parts.append(f"[voice] file_id={message.voice.file_id}")
    if message.audio:
        parts.append(f"[audio] file_id={message.audio.file_id}")
    if message.sticker:
        parts.append(f"[sticker] file_id={message.sticker.file_id}")

    return "\n".join(parts).strip() or "<без текста>"


# ========= УВЕДОМЛЕНИЯ О ВКЛ/ВЫКЛ БИЗНЕС-СВЯЗИ =========
@router.business_connection()
async def on_business_connection(bc: BusinessConnection, bot):
    await _upsert_bc(bc)

    rights = getattr(bc, "rights", None)
    can_reply = getattr(rights, "can_reply", None) if rights else None

    status = "ВКЛЮЧИЛ" if bc.is_enabled and (can_reply is not False) else "ВЫКЛЮЧИЛ"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    text = (
        f"🔔 <b>{status} бизнес-бота</b>\n"
        f"Менеджер: <code>{bc.user.full_name}</code>\n"
        f"manager_user_id: <code>{bc.user.id}</code>\n"
        f"bc_id: <code>{bc.id}</code>\n"
        f"is_enabled: <code>{bc.is_enabled}</code>\n"
        f"can_reply: <code>{'None' if can_reply is None else can_reply}</code>\n"
        f"⏱ {ts}"
    )
    await _notify_group(bot, text)


# ========= ДУБЛИРОВАНИЕ ПЕРЕПИСКИ В СДЕЛКУ =========
@router.business_message()
async def on_business_message(message: Message, bot):
    # пишем только private диалоги менеджер<->клиент
    if not _is_private_chat(message):
        return

    bc_id = getattr(message, "business_connection_id", None)

    # проверяем, что связь включена и можно отвечать
    bc_state = await _ensure_bc_cached(bot, bc_id)
    if bc_state and (not bc_state["is_enabled"] or bc_state["can_reply"] is False):
        await _notify_group(
            bot,
            (
                "⚠️ Business: сообщение пропущено — связь отключена\n"
                f"bc_id: <code>{bc_id}</code>\n"
                f"chat_id (client): <code>{message.chat.id}</code>"
            ),
        )
        return

    # гарантируем сделку (или None)
    deal_id = await ensure_deal_id_for_private_chat(bot, message)
    if not deal_id:
        # по вашему требованию "только в сделку" — если сделки нет, не пишем
        await _notify_b_group(
            bot,
            (
                "⚠️ Business: сделка не найдена/не создана — комментарий не записан\n"
                f"client_tg_id: <code>{message.chat.id}</code>"
            ),
        )
        return

    client_id = int(message.chat.id)

    # В Business-диалоге from_user может быть менеджером или клиентом
    is_incoming_from_client = bool(message.from_user and message.from_user.id == client_id)
    direction = "Сообщение клиента" if is_incoming_from_client else "Сообщение менеджера"
    manager_suffix = ""

    if message.from_user and not is_incoming_from_client:
        manager_suffix = f" ({message.from_user.full_name})"
    # ✅ НОВОЕ: если клиент пишет и он в "плохой" стадии — переносим в 1 касание
    if is_incoming_from_client:
        try:
            await move_to_first_touch_if_needed(bitrix=bitrix, tg_id=client_id)
        except Exception:
            logger.exception("Business: stage guard failed client_id=%s", client_id)
    body = _format_message_for_bitrix(message)

    comment = (
        f"{direction}{manager_suffix} (Telegram Business):\n\n"
        f"{body}"
    )

    try:
        await bitrix.add_deal_timeline_comment(deal_id, comment)
    except Exception as e:
        logger.exception("Bitrix timeline add failed deal_id=%s: %s", deal_id, e)
        await _notify_group(
            bot,
            (
                "❌ Business: ошибка записи в Bitrix\n"
                f"deal_id: <code>{deal_id}</code>\n"
                f"client_tg_id: <code>{client_id}</code>"
            ),
        )
