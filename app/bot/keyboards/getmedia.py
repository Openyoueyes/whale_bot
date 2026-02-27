# app/bot/keyboards/getmedia.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_media_type_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="Фото", callback_data="getmedia:type:photo"),
            InlineKeyboardButton(text="Видео", callback_data="getmedia:type:video"),
        ],
        [
            InlineKeyboardButton(text="Аудио", callback_data="getmedia:type:audio"),
            InlineKeyboardButton(text="Голос", callback_data="getmedia:type:voice"),
        ],
        [
            InlineKeyboardButton(text="Документ", callback_data="getmedia:type:document"),
            InlineKeyboardButton(text="Стикер", callback_data="getmedia:type:sticker"),
        ],
        [
            InlineKeyboardButton(text="GIF/Анимация", callback_data="getmedia:type:animation"),
            InlineKeyboardButton(text="Видео-нота", callback_data="getmedia:type:video_note"),
        ],
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="fsm:cancel"),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)