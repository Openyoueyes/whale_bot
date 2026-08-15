# app/bot/keyboards/dialog.py

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

NO_DEAL_TOKEN = "no_deal"


def reply_to_client_kb(tg_id: int, deal_id: str | None) -> InlineKeyboardMarkup:
    """
    Кнопка «Ответить клиенту» под карточкой в чате менеджера.
    callback_data: reply_to_client:{tg_id}:{deal_id|no_deal}
    """
    deal_part = deal_id or NO_DEAL_TOKEN
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✉️ Ответить клиенту",
                    callback_data=f"reply_to_client:{tg_id}:{deal_part}",
                )
            ]
        ]
    )
