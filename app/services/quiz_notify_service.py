# app/services/quiz_notify_service.py
from __future__ import annotations

from aiogram import Bot

from app.bot.keyboards.dialog import reply_to_client_kb
from app.services.bitrix_presenter import load_deal_card
from app.services.notify_service import notify_managers


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
    card = await load_deal_card(tg_id)

    text = (
        "🧩 <b>Клиент прошёл тест</b>\n"
        "----------------------------------------\n"
        f"{card.link_text}\n"
        "----------------------------------------\n"
        f"<b>Ответственный:</b> {card.responsible}\n"
        f"Тег: {card.tag_text}\n"
        f"<b>TG ID:</b> <code>{tg_id}</code>\n"
        f"<b>Username:</b> @{username or 'нет'}\n"
        f"<b>Имя:</b> {full_name}\n\n"
        f"<b>Уровень:</b> {level}\n"
        f"<b>Score:</b> {score}\n\n"
        f"<b>Ответы:</b>\n{answers_text}"
    )

    await notify_managers(bot, text, reply_markup=reply_to_client_kb(tg_id, card.deal_id))


async def send_quiz_choice_notification(
    *,
    bot: Bot,
    tg_id: int,
    username: str | None,
    full_name: str,
    choice_text: str,
) -> None:
    card = await load_deal_card(tg_id)

    text = (
        "🎯 <b>Клиент выбрал направление</b>\n"
        "----------------------------------------\n"
        f"{card.link_text}\n"
        "----------------------------------------\n"
        f"Тег: {card.tag_text}\n"
        f"<b>Ответственный:</b> {card.responsible}\n"
        f"<b>TG ID:</b> <code>{tg_id}</code>\n"
        f"<b>Username:</b> @{username or 'нет'}\n"
        f"<b>Имя:</b> {full_name}\n\n"
        f"<b>Выбор:</b> {choice_text}"
    )

    await notify_managers(bot, text, reply_markup=reply_to_client_kb(tg_id, card.deal_id))
