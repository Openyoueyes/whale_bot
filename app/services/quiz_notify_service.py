from __future__ import annotations

import logging
from typing import Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.config import GROUP_CHAT_MESSAGES_BOT_ID, ADMIN_IDS
from app.integrations.bitrix.client import BitrixClient

logger = logging.getLogger(__name__)
bitrix_client = BitrixClient()


def _gift_name(gift: str | None) -> str:
    if gift == "session":
        return "Онлайн-сессия"
    if gift == "consult":
        return "Консультация"
    return "не выбран"


async def _get_deal_id_for_tg(tg_id: int) -> str | None:
    """
    Находим сделку:
    1) по UF TG_ID в сделках
    2) fallback: через lead (по TG_ID) -> deal по LEAD_ID
    """
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None

    if deal and deal.get("ID"):
        return str(deal["ID"])

    try:
        leads = await bitrix_client.list_leads_by_telegram_id(tg_id)
    except Exception:
        leads = []

    if not leads:
        return None

    try:
        lead_id = int(sorted(leads, key=lambda x: int(x["ID"]))[0]["ID"])
    except Exception:
        return None

    try:
        deals = await bitrix_client.list_deals_by_lead_id(lead_id)
    except Exception:
        deals = []

    if deals:
        return str(deals[0]["ID"])
    return None


async def _get_deal_link_and_responsible(deal_id: str | None) -> Tuple[str, str]:
    """
    Возвращает:
    - deal_link_text (HTML)
    - responsible_text
    """
    deal_link_text = "Сделка не найдена"
    responsible_text = "не назначен"

    if not deal_id:
        return deal_link_text, responsible_text

    try:
        link = bitrix_client.make_deal_link(deal_id)
        deal_link_text = f'<a href="{link}">Перейти в сделку</a>'
    except Exception:
        deal_link_text = "Сделка найдена (ссылка недоступна)"

    try:
        full_deal = await bitrix_client.get_deal(deal_id)
        assigned_id = full_deal.get("ASSIGNED_BY_ID")
        if assigned_id:
            u = await bitrix_client.get_user(assigned_id)
            first = (u.get("NAME") or "").strip()
            last = (u.get("LAST_NAME") or "").strip()
            login = (u.get("LOGIN") or "").strip()
            full = (first + " " + last).strip()
            responsible_text = full or login or str(assigned_id)
    except Exception:
        responsible_text = "не назначен"

    return deal_link_text, responsible_text


def _kb_reply_to_client(tg_id: int, deal_id: str | None) -> InlineKeyboardMarkup:
    deal_part = deal_id if deal_id else "no_deal"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Ответить клиенту", callback_data=f"reply_to_client:{tg_id}:{deal_part}")]
        ]
    )


async def _send_to_admins_and_group(
    *,
    bot: Bot,
    tg_id: int,
    deal_id: str | None,
    text: str,
) -> None:
    """
    Как в dialog_service:
    - админам: с кнопкой
    - в группу: без кнопки
    """
    # 1) Админам — с кнопкой
    kb = _kb_reply_to_client(tg_id, deal_id)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=kb,
            )
        except Exception:
            continue

    # 2) В группу — БЕЗ кнопки
    if GROUP_CHAT_MESSAGES_BOT_ID:
        try:
            await bot.send_message(
                GROUP_CHAT_MESSAGES_BOT_ID,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("quiz notify send to group failed tg_id=%s", tg_id)


async def notify_quiz_completed_no_phone(
    *,
    bot: Bot,
    tg_id: int,
    username: str | None,
    full_name: str,
    level: str,
    score: int,
    gift: str | None,
) -> None:
    """
    Уведомление №1: клиент выбрал подарок (контакта ещё нет)
    """
    deal_id = await _get_deal_id_for_tg(tg_id)
    deal_link_text, responsible_text = await _get_deal_link_and_responsible(deal_id)

    text = (
        "🧩 <b>Клиент прошёл квиз</b>\n"
        "----------------------------------------\n"
        f"{deal_link_text}\n"
        "----------------------------------------\n"
        f"<b>Ответственный:</b> {responsible_text}\n"
        f"<b>TG ID:</b> <code>{tg_id}</code>\n"
        f"<b>Username:</b> @{username or 'нет'}\n"
        f"<b>Имя:</b> {full_name}\n\n"
        f"<b>Уровень:</b> {level}\n"
        f"<b>Score:</b> {score}\n"
        f"<b>Подарок:</b> {_gift_name(gift)}\n"
        f"<b>Контакт:</b> ещё не оставлен"
    )

    try:
        await _send_to_admins_and_group(
            bot=bot,
            tg_id=tg_id,
            deal_id=deal_id,
            text=text,
        )
    except Exception:
        logger.exception("notify_quiz_completed_no_phone failed tg_id=%s", tg_id)


async def notify_quiz_phone_received(
    *,
    bot: Bot,
    tg_id: int,
    username: str | None,
    full_name: str,
    phone: str,
    level: str,
    score: int,
    gift: str | None,
) -> None:
    """
    Уведомление №2: клиент оставил телефон
    """
    deal_id = await _get_deal_id_for_tg(tg_id)
    deal_link_text, responsible_text = await _get_deal_link_and_responsible(deal_id)

    text = (
        "📞 <b>Клиент оставил контакт после квиза</b>\n"
        "----------------------------------------\n"
        f"{deal_link_text}\n"
        "----------------------------------------\n"
        f"<b>Ответственный:</b> {responsible_text}\n"
        f"<b>TG ID:</b> <code>{tg_id}</code>\n"
        f"<b>Username:</b> @{username or 'нет'}\n"
        f"<b>Имя:</b> {full_name}\n\n"
        f"<b>Телефон:</b> <code>{phone}</code>\n"
        f"<b>Уровень:</b> {level}\n"
        f"<b>Score:</b> {score}\n"
        f"<b>Подарок:</b> {_gift_name(gift)}"
    )

    try:
        await _send_to_admins_and_group(
            bot=bot,
            tg_id=tg_id,
            deal_id=deal_id,
            text=text,
        )
    except Exception:
        logger.exception("notify_quiz_phone_received failed tg_id=%s", tg_id)