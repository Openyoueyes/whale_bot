# app/services/quiz_notify_service.py
from __future__ import annotations

import logging
from typing import Tuple

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from app.config import GROUP_CHAT_MESSAGES_BOT_ID, ADMIN_IDS
from app.integrations.bitrix.client import BitrixClient

logger = logging.getLogger(__name__)
bitrix_client = BitrixClient()


def _kb_reply_to_client(tg_id: int, deal_id: str | None) -> InlineKeyboardMarkup:
    deal_part = deal_id if deal_id else "no_deal"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Ответить клиенту", callback_data=f"reply_to_client:{tg_id}:{deal_part}")]
        ]
    )


async def _get_deal_id_for_tg(tg_id: int) -> str | None:
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None
    if deal and deal.get("ID"):
        return str(deal["ID"])
    return None


async def _get_deal_link_and_responsible(deal_id: str | None) -> Tuple[str, str]:
    deal_link_text = "Сделка не найдена"
    responsible_text = "не назначен"

    if not deal_id:
        return deal_link_text, responsible_text

    try:
        link = bitrix_client.make_deal_link(deal_id)
        deal_link_text = f'<a href="{link}">Перейти в сделку</a>'
    except Exception:
        pass

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
        pass

    return deal_link_text, responsible_text


async def send_quiz_result_notification(
    *,
    bot: Bot,
    tg_id: int,
    username: str | None,
    full_name: str,
    level: str,
    score: int,
    answers_text: str,
) -> None:
    deal_id = await _get_deal_id_for_tg(tg_id)
    deal_link_text, responsible_text = await _get_deal_link_and_responsible(deal_id)

    text = (
        "🧩 <b>Клиент прошёл тест</b>\n"
        "----------------------------------------\n"
        f"{deal_link_text}\n"
        "----------------------------------------\n"
        f"<b>Ответственный:</b> {responsible_text}\n"
        f"<b>TG ID:</b> <code>{tg_id}</code>\n"
        f"<b>Username:</b> @{username or 'нет'}\n"
        f"<b>Имя:</b> {full_name}\n\n"
        f"<b>Уровень:</b> {level}\n"
        f"<b>Score:</b> {score}\n\n"
        f"<b>Ответы:</b>\n{answers_text}"
    )

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

    if GROUP_CHAT_MESSAGES_BOT_ID:
        try:
            await bot.send_message(
                GROUP_CHAT_MESSAGES_BOT_ID,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("quiz result notify send to group failed tg_id=%s", tg_id)


async def send_quiz_choice_notification(
    *,
    bot: Bot,
    tg_id: int,
    username: str | None,
    full_name: str,
    choice_text: str,
) -> None:
    deal_id = await _get_deal_id_for_tg(tg_id)
    deal_link_text, responsible_text = await _get_deal_link_and_responsible(deal_id)

    text = (
        "🎯 <b>Клиент выбрал направление</b>\n"
        "----------------------------------------\n"
        f"{deal_link_text}\n"
        "----------------------------------------\n"
        f"<b>Ответственный:</b> {responsible_text}\n"
        f"<b>TG ID:</b> <code>{tg_id}</code>\n"
        f"<b>Username:</b> @{username or 'нет'}\n"
        f"<b>Имя:</b> {full_name}\n\n"
        f"<b>Выбор:</b> {choice_text}"
    )

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

    if GROUP_CHAT_MESSAGES_BOT_ID:
        try:
            await bot.send_message(
                GROUP_CHAT_MESSAGES_BOT_ID,
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("quiz choice notify send to group failed tg_id=%s", tg_id)