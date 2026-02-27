# app/bot/keyboards/common.py

from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton


def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    """
    Универсальная клавиатура с кнопкой '❌ Отмена'
    для любых FSM-сценариев (клиент и админ).
    """
    keyboard = [
        [KeyboardButton(text="❌ Отмена")]
    ]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )

def cancel_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="fsm:cancel")]
        ]
    )