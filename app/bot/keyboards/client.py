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
            KeyboardButton(text="💰 Whale Профит"),
            KeyboardButton(text="🤖 Торговые роботы"),
        ],
        [
            KeyboardButton(text="🎁 Бонус"),
            KeyboardButton(text="📞 Связь с менеджером"),
        ],
    ]

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def get_subscribe_inline_keyboard() -> InlineKeyboardMarkup:
    """
    Инлайн-клавиатура для открытия доступа через подписку.
    """
    keyboard = [
        [
            InlineKeyboardButton(
                text="📣 Подписаться на канал",
                url=CHANNEL_URL,
            )
        ],
        [
            InlineKeyboardButton(
                text="✅ Я подписался — открыть доступ",
                callback_data="subscription:check",
            )
        ],
    ]

    return InlineKeyboardMarkup(inline_keyboard=keyboard)
