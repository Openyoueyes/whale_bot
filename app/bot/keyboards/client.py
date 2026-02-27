# app/bot/keyboards/client.py

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from app.config import CHANNEL_URL


def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Главная реплай-клавиатура для клиента.
    """
    keyboard = [
        [
            KeyboardButton(text="🤖 Роботы"),
            KeyboardButton(text="💰 Закрытый канал"),
        ],
        [
            KeyboardButton(text="🎁 Бонус"),
            KeyboardButton(text="📊 Тест на трейдера"),
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def get_subscribe_inline_keyboard() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура с кнопкой подписки на канал.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="📣 Подписаться на канал",
                url=CHANNEL_URL,
            )
        ]
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
