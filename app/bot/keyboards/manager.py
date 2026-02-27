# app/bot/keyboards/manager.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_manager_keyboard(url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✉️ Написать менеджеру", url=url)]
        ]
    )
