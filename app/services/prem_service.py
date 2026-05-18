# app/bot/services/prem_service.py

from __future__ import annotations

from aiogram import Bot
from aiogram.types import User, InlineKeyboardMarkup, InlineKeyboardButton

from app.config import ADMIN_IDS, GROUP_CHAT_MESSAGES_BOT_ID
from app.integrations.bitrix.client import BitrixClient

bitrix_client = BitrixClient()


def _reply_to_client_keyboard(tg_id: int, deal_id: str | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✉️ Ответить клиенту",
                    callback_data=f"reply_to_client:{tg_id}:{deal_id or 'no_deal'}",
                )
            ]
        ]
    )


async def create_prem_request(bot: Bot, tg_user: User, source: str) -> None:
    """
    “Заявка на обучение”:
    - находим сделку по tg_id,
    - пишем комментарий в таймлайн сделки,
    - уведомляем админов/группу + кнопка “Ответить клиенту”.
    """
    tg_id = tg_user.id
    username = tg_user.username or "нет"
    full_name = tg_user.full_name

    deal = None
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None

    deal_id: str | None = str(deal["ID"]) if deal else None
    tag_value: str | None = str(deal["UF_CRM_1745855127"]) if deal else None
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

    if deal_id:
        deal_link = bitrix_client.make_deal_link(deal_id)
        deal_link_text = f'<a href="{deal_link}">Перейти в сделку</a>'

        comment = (
            "Заявка на прем из Telegram бота\n\n"
            f"Источник: {source}\n"
            f"TG ID: {tg_id}\n"
            f"Username: @{username}\n"
            f"Имя: {full_name}"
        )
        try:
            await bitrix_client.add_deal_timeline_comment(deal_id, comment)
        except Exception:
            pass

    notify_text = (
        "📩 <b>Новая заявка на прем</b>\n\n"
        f"{deal_link_text}\n\n"
        f"Тег: {tag_value or 'нет тега'}\n"
        f"<b>Ответсвенный:</b> {responsible_text}\n"
        f"<b>Источник:</b> {source}\n"
        f"<b>TG ID:</b> <code>{tg_id}</code>\n"
        f"<b>Username:</b> @{username}\n"
        f"<b>Имя:</b> {full_name}"
    )

    reply_kb = _reply_to_client_keyboard(tg_id=tg_id, deal_id=deal_id)

    # Админам
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                notify_text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=reply_kb,
            )
        except Exception:
            pass

    # В группу (если нужно)
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
