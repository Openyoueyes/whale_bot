# app/bot/keyboards/quiz.py

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder


def get_quiz_start_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎯 Определить свой уровень трейдера", callback_data="quiz:start")
    return kb.as_markup()


def get_quiz_answer_inline_kb(q_key: str, options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """
    options: [(text, value), ...]
    callback_data: quiz:a:<q_key>:<value>
    """
    kb = InlineKeyboardBuilder()
    for text, value in options:
        kb.button(text=text, callback_data=f"quiz:a:{q_key}:{value}")
    kb.adjust(1)
    kb.button(text="⛔️ Прервать тест", callback_data="quiz:cancel")
    return kb.as_markup()


def get_quiz_gift_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🎁 Онлайн-сессия с трейдером", callback_data="quiz:gift:session")
    kb.button(text="🎁 Консультация", callback_data="quiz:gift:consult")
    kb.adjust(1)
    kb.button(text="⛔️ Прервать тест", callback_data="quiz:cancel")
    return kb.as_markup()


def get_share_contact_kb() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.button(text="📱 Поделиться телефоном", request_contact=True)
    kb.button(text="⛔️ Отмена", request_contact=False)
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True, one_time_keyboard=True)