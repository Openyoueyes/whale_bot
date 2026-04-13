# app/bot/keyboards/prem.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_prem_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Получить доступ", callback_data="prem:apply")]
        ]
    )

def get_prem_post_apply_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура после отправки заявки: только 'Назад'
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="robots:back")],
        ]
    )
