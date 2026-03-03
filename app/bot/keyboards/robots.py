# app/bot/keyboards/robots.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_robot_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🥇 WT_AI", callback_data="robots:wt_ai")],
            [InlineKeyboardButton(text="🥈 WT_SAFETREND", callback_data="robots:wt_safe")],
            [InlineKeyboardButton(text="🥉 WT_QUAN", callback_data="robots:wt_quant")],

        ]
    )


def get_robot_detail_keyboard(product_key: str) -> InlineKeyboardMarkup:
    rows = []

    if product_key == "wt_ai":
        rows.append([InlineKeyboardButton(text="✅ Получить робота", callback_data="robots:wt_ai:apply")])

    if product_key == "wt_safe":
        rows.append([InlineKeyboardButton(text="✅ Получить робота", callback_data="robots:wt_safe:apply")])

    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="robots:back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def get_robot_post_apply_keyboard() -> InlineKeyboardMarkup:
    """
    Клавиатура после отправки заявки: только 'Назад'
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="products:back")],
        ]
    )
