# app/bot/keyboards/quiz.py

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from app.bot.routers.client.quiz import QuizQuestion


def get_quiz_choice_inline_kb(*, recommended: str | None = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()

    manual_text = "🧑‍💻 Ручная торговля"
    robot_text = "🤖 Автоматическая торговля (роботы)"

    if recommended == "manual":
        manual_text = "✅ " + manual_text
    elif recommended == "robot":
        robot_text = "✅ " + robot_text

    kb.button(text=manual_text, callback_data="quiz:choice:manual")
    kb.button(text=robot_text, callback_data="quiz:choice:robot")
    kb.adjust(1)
    kb.button(text="⛔️ Прервать тест", callback_data="quiz:cancel")
    return kb.as_markup()


def get_quiz_start_inline_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="🧠 Пройти проф-тест трейдера", callback_data="quiz:start")
    kb.button(text="⛔️ Отмена", callback_data="quiz:cancel")
    kb.adjust(1)
    return kb.as_markup()


def get_quiz_answer_inline_kb(question: QuizQuestion) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for text, value in question.options:
        kb.button(text=text, callback_data=f"quiz:answer:{question.key}:{value}")
    kb.adjust(1)
    return kb.as_markup()
