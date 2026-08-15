# app/services/request_service.py
"""
Заявки клиента из витрин бота (Премиум, роботы и т.п.).

Раньше это были два почти идентичных файла (prem_service / robots_service),
отличавшихся только заголовками. Теперь один сценарий с параметром.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import User

from app.bot.keyboards.dialog import reply_to_client_kb
from app.services.bitrix_presenter import comment_safe, load_deal_card
from app.services.notify_service import notify_managers


async def create_client_request(
    bot: Bot,
    tg_user: User,
    *,
    source: str,
    notify_title: str,
    comment_title: str,
) -> None:
    """
    Общий сценарий заявки:
      - находим сделку клиента,
      - пишем комментарий в таймлайн,
      - уведомляем менеджеров с кнопкой «Ответить клиенту».
    """
    tg_id = tg_user.id
    username = tg_user.username or "нет"
    full_name = tg_user.full_name

    card = await load_deal_card(tg_id)

    await comment_safe(
        card.deal_id,
        (
            f"{comment_title}\n\n"
            f"Источник: {source}\n"
            f"Тег: {card.tag_text}\n"
            f"TG ID: {tg_id}\n"
            f"Username: @{username}\n"
            f"Имя: {full_name}\n"
            f"Ответственный: {card.responsible}"
        ),
    )

    await notify_managers(
        bot,
        (
            f"{notify_title}\n\n"
            f"{card.link_text}\n\n"
            f"Тег: {card.tag_text}\n"
            f"<b>Ответственный:</b> {card.responsible}\n"
            f"<b>Источник:</b> {source}\n"
            f"<b>TG ID:</b> <code>{tg_id}</code>\n"
            f"<b>Username:</b> @{username}\n"
            f"<b>Имя:</b> {full_name}"
        ),
        reply_markup=reply_to_client_kb(tg_id, card.deal_id),
    )


async def create_prem_request(bot: Bot, tg_user: User, source: str) -> None:
    """Заявка из раздела «Whale Профит»."""
    await create_client_request(
        bot,
        tg_user,
        source=source,
        notify_title="📩 <b>Новая заявка на прем</b>",
        comment_title="Заявка на прем из Telegram бота",
    )


async def create_product_request(bot: Bot, tg_user: User, source: str) -> None:
    """Заявка из раздела «Торговые роботы»."""
    await create_client_request(
        bot,
        tg_user,
        source=source,
        notify_title="🆕 <b>Новая заявка (Роботы)</b>",
        comment_title="Заявка из Telegram бота (Роботы)",
    )
