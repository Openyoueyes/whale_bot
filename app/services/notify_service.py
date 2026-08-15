# app/services/notify_service.py
"""
Рассылка служебных уведомлений менеджерам: личные сообщения админам + группа.
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup

from app.config import ADMIN_IDS, GROUP_CHAT_MESSAGES_BOT_ID, GROUP_CHAT_MESSAGES_ID

logger = logging.getLogger(__name__)


async def notify_managers(
    bot: Bot,
    text: str,
    *,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    group_chat_id: Optional[int] = None,
) -> None:
    """
    Шлём карточку каждому админу и (если задан) в рабочую группу.
    Кнопки идут только в личку: в группе они всё равно не сработают,
    потому что FSM ответа привязан к конкретному менеджеру.
    """
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.warning("Не удалось отправить уведомление админу %s", admin_id)

    chat_id = GROUP_CHAT_MESSAGES_BOT_ID if group_chat_id is None else group_chat_id
    if not chat_id:
        return

    try:
        await bot.send_message(
            chat_id,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.warning("Не удалось отправить уведомление в группу %s", chat_id)


async def notify_leads_group(bot: Bot, text: str) -> None:
    """Отдельная группа под уведомления о новых лидах."""
    if not GROUP_CHAT_MESSAGES_ID:
        return
    try:
        await bot.send_message(
            GROUP_CHAT_MESSAGES_ID,
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.warning("Не удалось отправить уведомление о лиде в группу")
