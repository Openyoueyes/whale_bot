from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_reviews_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎥 Отзыв 1", callback_data="results:review:1")],
            [InlineKeyboardButton(text="🎥 Отзыв 2", callback_data="results:review:2")],
            [InlineKeyboardButton(text="🎥 Отзыв 3", callback_data="results:review:3")],
            [InlineKeyboardButton(text="🎥 Отзыв 4", callback_data="results:review:4")],
        ]
    )


def get_review_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="results:back")],
        ]
    )
