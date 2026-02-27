# app/bot/keyboards/team.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_team_list_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Андрей Миклушевский", callback_data="team:andrey")],
            [InlineKeyboardButton(text="Антон Ган", callback_data="team:anton")],
        ]
    )


def get_team_profile_keyboard(member_key: str) -> InlineKeyboardMarkup:
    rows = []
    if member_key == "anton":
        rows.append([InlineKeyboardButton(text="📩 Записаться на обучение", callback_data="team:anton:apply")])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="team:back")])

    return InlineKeyboardMarkup(inline_keyboard=rows)
