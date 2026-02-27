from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить / обновить", callback_data="triggers:add")],
            [InlineKeyboardButton(text="📋 Список", callback_data="triggers:list")],
            [InlineKeyboardButton(text="🗑 Удалить", callback_data="triggers:del")],
        ]
    )
