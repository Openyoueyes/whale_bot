# app/services/dialog_service.py

from __future__ import annotations

from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from app.config import ADMIN_IDS, GROUP_CHAT_MESSAGES_BOT_ID
from app.integrations.bitrix.client import BitrixClient

bitrix_client = BitrixClient()


def _reply_kb(tg_id: int, deal_id: str | None) -> InlineKeyboardMarkup:
    deal_part = deal_id if deal_id else "no_deal"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Ответить клиенту", callback_data=f"reply_to_client:{tg_id}:{deal_part}")]
        ]
    )


def _format_message_for_bitrix(message: Message) -> str:
    """
    Универсальный “дамп” сообщения: текст/caption + вложения.
    """
    text = message.text or message.caption or ""
    parts: list[str] = []

    if text:
        parts.append(text)

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
    if message.animation:
        parts.append(f"[animation] file_id={message.animation.file_id}")

    return "\n".join(parts).strip() or "<без текста>"


async def process_client_message(bot: Bot, message: Message) -> None:
    """
    Любое сообщение клиента (текст/фото/видео/голос/файл/...):
    - ищем сделку
    - пишем в таймлайн сделки
    - шлём админам "карточку" + копируем оригинал сообщения
    """
    from_user = message.from_user
    if not from_user:
        return

    tg_id = from_user.id

    # 1) ищем сделку
    deal = None
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None

    deal_id: str | None = str(deal["ID"]) if deal else None
    deal_link_text = "Сделка не найдена"
    responsible_text = "не назначен"

    if deal_id:
        deal_link = bitrix_client.make_deal_link(deal_id)
        deal_link_text = f'<a href="{deal_link}">Перейти в сделку</a>'

        # получаем ответственного
        try:
            full_deal = await bitrix_client.get_deal(deal_id)
            assigned_id = full_deal.get("ASSIGNED_BY_ID")

            if assigned_id:
                user_data = await bitrix_client.get_user(assigned_id)
                first = (user_data.get("NAME") or "").strip()
                last = (user_data.get("LAST_NAME") or "").strip()
                login = (user_data.get("LOGIN") or "").strip()
                full_name = (first + " " + last).strip()
                responsible_text = full_name or login or str(assigned_id)

        except Exception:
            responsible_text = "не назначен"

    # 2) Bitrix: логируем содержимое
    if deal_id:
        body = _format_message_for_bitrix(message)
        comment_text = (
            "Сообщение от клиента из Telegram бота:\n\n"
            f"{body}"
        )
        try:
            await bitrix_client.add_deal_timeline_comment(deal_id, comment_text)
        except Exception:
            pass

    kb = _reply_kb(tg_id=tg_id, deal_id=deal_id)

    # 3) Карточка для админов
    admin_card = (
        "Новое сообщение от клиента\n"
        "----------------------------------------\n"
        f"{deal_link_text}\n"
        "----------------------------------------\n"
        f"Ответственный: {responsible_text}\n"
        f"TG ID: <code>{tg_id}</code>\n"
        f"Username: @{from_user.username or 'нет'}\n"
        f"Имя: {from_user.full_name}\n"
        "👇"
    )

    # 4) Админам
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                admin_card,
                reply_markup=kb,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

            await bot.copy_message(
                chat_id=admin_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )

        except Exception:
            continue

    # 5) Клиенту подтверждение
    try:
        await message.answer("Сообщение передано, ожидайте ответ менеджера.")
    except Exception:
        pass

    # 6) В группу
    if GROUP_CHAT_MESSAGES_BOT_ID:
        try:
            await bot.send_message(
                GROUP_CHAT_MESSAGES_BOT_ID,
                admin_card,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

            await bot.copy_message(
                chat_id=GROUP_CHAT_MESSAGES_BOT_ID,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )

        except Exception:
            pass
