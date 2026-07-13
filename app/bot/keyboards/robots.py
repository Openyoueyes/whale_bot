# app/bot/keyboards/robots.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_robot_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥇 WT_AI", callback_data="robots:wt_ai")],
            [InlineKeyboardButton(text="🥈 WT_BREAKOUTGOLD", callback_data="robots:wt_breakoutgold")],
        ]
    )


def get_robot_detail_keyboard(product_key: str) -> InlineKeyboardMarkup:
    rows = []

    if product_key == "wt_ai":
        rows.append([InlineKeyboardButton(text="✅ Получить робота", callback_data="robots:wt_ai:apply")])

    if product_key == "wt_breakoutgold":
        rows.append([InlineKeyboardButton(text="✅ Получить робота", callback_data="robots:wt_breakoutgold:apply")])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="robots:back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_robot_post_apply_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура после отправки заявки: только 'Назад'
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="robots:back")],
        ]
    )
