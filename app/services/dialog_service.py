# app/services/dialog_service.py

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import Message

from app.bot.keyboards.dialog import reply_to_client_kb
from app.config import ADMIN_IDS, GROUP_CHAT_MESSAGES_BOT_ID
from app.services.bitrix_presenter import DealCard, build_deal_card, comment_safe, load_deal_card
from app.services.message_formatters import format_message_for_bitrix

logger = logging.getLogger(__name__)


async def process_client_message(
    bot: Bot,
    message: Message,
    *,
    deal: Optional[Dict[str, Any]] = None,
) -> DealCard:
    """
    Любое сообщение клиента (текст/фото/видео/голос/файл/...):
    - находим сделку,
    - пишем в таймлайн,
    - шлём менеджерам карточку + копию оригинала.

    deal — уже загруженная сделка (её отдаёт BitrixStageGuardMiddleware),
    чтобы не спрашивать Bitrix дважды на одно сообщение.

    Возвращает карточку сделки: вызывающий код дописывает в тот же таймлайн
    (например, авто-ответ по триггеру) без повторного поиска сделки.
    """
    from_user = message.from_user
    if not from_user:
        return DealCard()

    tg_id = from_user.id

    card = await build_deal_card(deal) if deal else await load_deal_card(tg_id)

    await comment_safe(
        card.deal_id,
        "Сообщение от клиента из Telegram бота:\n\n" f"{format_message_for_bitrix(message)}",
    )

    admin_card = (
        "Новое сообщение от клиента\n"
        "----------------------------------------\n"
        f"{card.link_text}\n"
        "----------------------------------------\n"
        f"Тег: {card.tag_text}\n"
        f"Ответственный: {card.responsible}\n"
        f"TG ID: <code>{tg_id}</code>\n"
        f"Username: @{from_user.username or 'нет'}\n"
        f"Имя: {from_user.full_name}\n"
        "👇"
    )

    kb = reply_to_client_kb(tg_id, card.deal_id)

    # Менеджерам: карточка + копия исходного сообщения (чтобы видеть медиа как есть).
    targets: list[tuple[int, bool]] = [(admin_id, True) for admin_id in ADMIN_IDS]
    if GROUP_CHAT_MESSAGES_BOT_ID:
        targets.append((GROUP_CHAT_MESSAGES_BOT_ID, False))

    for chat_id, with_kb in targets:
        try:
            await bot.send_message(
                chat_id,
                admin_card,
                reply_markup=kb if with_kb else None,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            await bot.copy_message(
                chat_id=chat_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id,
            )
        except Exception:
            logger.warning("Не удалось переслать сообщение клиента в чат %s", chat_id)

    try:
        await message.answer("Сообщение передано, ожидайте ответ менеджера.")
    except Exception:
        logger.warning("Не удалось подтвердить приём сообщения клиенту %s", tg_id)

    return card
