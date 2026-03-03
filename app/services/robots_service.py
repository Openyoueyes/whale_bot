# app/services/product_service.py

from __future__ import annotations

from aiogram import Bot
from aiogram.types import User, InlineKeyboardMarkup, InlineKeyboardButton

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


async def create_product_request(bot: Bot, tg_user: User, source: str) -> None:
    """
    Заявка по продуктам:
    - находим сделку по tg_id (если есть),
    - получаем ответственного,
    - пишем коммент в таймлайн,
    - уведомляем админов/группу,
    - добавляем кнопку "Ответить клиенту".
    """
    tg_id = tg_user.id
    username = tg_user.username or "нет"
    full_name = tg_user.full_name

    # 1) Поиск сделки
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None

    deal_id: str | None = str(deal["ID"]) if deal else None
    responsible_text = "не назначен"
    deal_link_text = "Сделка не найдена"

    # 2) Если есть сделка — получаем ссылку и ответственного
    if deal_id:
        deal_link = bitrix_client.make_deal_link(deal_id)
        deal_link_text = f'<a href="{deal_link}">Перейти в сделку</a>'

        try:
            full_deal = await bitrix_client.get_deal(deal_id)
            assigned_id = full_deal.get("ASSIGNED_BY_ID")

            if assigned_id:
                user_data = await bitrix_client.get_user(assigned_id)
                first = (user_data.get("NAME") or "").strip()
                last = (user_data.get("LAST_NAME") or "").strip()
                login = (user_data.get("LOGIN") or "").strip()
                full = (first + " " + last).strip()
                responsible_text = full or login or str(assigned_id)

        except Exception:
            responsible_text = "не назначен"

    # 3) Комментарий в Bitrix
    if deal_id:
        comment = (
            "Заявка из Telegram бота (Роботы)\n\n"
            f"Источник: {source}\n"
            f"TG ID: {tg_id}\n"
            f"Username: @{username}\n"
            f"Имя: {full_name}\n"
            f"Ответственный: {responsible_text}"
        )
        try:
            await bitrix_client.add_deal_timeline_comment(deal_id, comment)
        except Exception:
            pass

    # 4) Уведомление админам
    notify_text = (
        "🆕 <b>Новая заявка (Роботы)</b>\n\n"
        f"{deal_link_text}\n\n"
        f"<b>Ответственный:</b> {responsible_text}\n"
        f"<b>Источник:</b> {source}\n"
        f"<b>TG ID:</b> <code>{tg_id}</code>\n"
        f"<b>Username:</b> @{username}\n"
        f"<b>Имя:</b> {full_name}"
    )

    kb = _reply_kb(tg_id=tg_id, deal_id=deal_id)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                notify_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=kb,
            )
        except Exception:
            pass

    # 5) В группу
    if GROUP_CHAT_MESSAGES_BOT_ID:
        try:
            await bot.send_message(
                GROUP_CHAT_MESSAGES_BOT_ID,
                notify_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            pass