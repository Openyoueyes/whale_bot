# app/bot/routers/client/prem.py
from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, func

from app.db.session import async_session_maker
from app.db.models import QuizSession, QuizAnswer
from app.bot.keyboards.quiz import (
    get_quiz_answer_inline_kb,
    get_quiz_start_inline_kb,
    get_quiz_choice_inline_kb,
)
from app.integrations.bitrix.client import BitrixClient
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed
from app.services.quiz_notify_service import notify_quiz_completed_no_phone

logger = logging.getLogger(__name__)
router = Router(name="client-quiz")

bitrix_client = BitrixClient()


# ============================================================
# QUIZ STRUCTURE
# ============================================================

@dataclass(frozen=True)
class QuizQuestion:
    key: str
    title: str
    options: list[tuple[str, str]]


QUIZ: list[QuizQuestion] = [
    QuizQuestion(
        key="goal",
        title="1️⃣ Что для вас сейчас важнее?",
        options=[
            ("Быстро запустить готовый алгоритм и не тратить много времени", "fast"),
            ("Разобраться и уметь торговать самому", "learn"),
        ],
    ),
    QuizQuestion(
        key="time",
        title="2️⃣ Сколько времени вы готовы уделять трейдингу в день?",
        options=[
            ("10–20 минут", "10"),
            ("30–60 минут", "30"),
            ("1–2 часа", "60"),
            ("2+ часа", "120"),
        ],
    ),
    QuizQuestion(
        key="experience",
        title="3️⃣ Ваш опыт на Forex?",
        options=[
            ("0 — ещё не торговал(а)", "0"),
            ("до 3 месяцев", "1"),
            ("3–12 месяцев", "2"),
            ("1+ год", "3"),
        ],
    ),
    QuizQuestion(
        key="style",
        title="4️⃣ Что вам ближе по формату?",
        options=[
            ("Хочу чёткий контроль (вход/выход руками)", "manual"),
            ("Хочу, чтобы система работала сама", "robot"),
        ],
    ),
    QuizQuestion(
        key="discipline",
        title="5️⃣ Как у вас с дисциплиной?",
        options=[
            ("Часто мешают эмоции", "hard"),
            ("Могу работать по регламенту", "ok"),
        ],
    ),
]


# ============================================================
# SCORING
# ============================================================

def _manual_score(ans: dict[str, str]) -> int:
    score = 0

    if ans.get("goal") == "learn":
        score += 2

    if ans.get("time") in {"60", "120"}:
        score += 2
    elif ans.get("time") == "30":
        score += 1

    if ans.get("experience") in {"2", "3"}:
        score += 2
    elif ans.get("experience") == "1":
        score += 1

    if ans.get("style") == "manual":
        score += 2

    if ans.get("discipline") == "ok":
        score += 1

    return score


def _recommendation(ans: dict[str, str]) -> str:
    return "manual" if _manual_score(ans) >= 6 else "robot"


def _rec_title(rec: str) -> str:
    return "🧑‍💻 Ручная торговля на Forex" if rec == "manual" else "🤖 Автоматическая торговля (роботы)"


# ============================================================
# DB
# ============================================================

async def _reset_quiz(tg_id: int) -> None:
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        if qs:
            qs.step = 0
            qs.finished = False
            qs.gift = None
            qs.updated_at = datetime.utcnow()

        await session.execute(
            QuizAnswer.__table__.delete().where(QuizAnswer.tg_id == tg_id)
        )
        await session.commit()


async def _save_answer(tg_id: int, q_key: str, value: str) -> int:
    async with async_session_maker() as session:
        session.add(QuizAnswer(tg_id=tg_id, q_key=q_key, answer=value))
        await session.flush()

        cnt = await session.scalar(
            select(func.count()).select_from(QuizAnswer)
            .where(QuizAnswer.tg_id == tg_id)
        )

        qs = await session.get(QuizSession, tg_id)
        if qs:
            qs.step = int(cnt or 0)
            qs.updated_at = datetime.utcnow()

        await session.commit()
        return int(cnt or 0)


async def _load_answers_map(tg_id: int) -> dict[str, str]:
    async with async_session_maker() as session:
        res = await session.execute(
            QuizAnswer.__table__.select()
            .where(QuizAnswer.tg_id == tg_id)
        )
        rows = res.mappings().all()

    return {r["q_key"]: r["answer"] for r in rows}


async def _set_choice(tg_id: int, choice: str) -> None:
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        if qs:
            qs.gift = choice  # используем поле gift как storage выбора
            qs.finished = True
            qs.updated_at = datetime.utcnow()
            await session.commit()


# ============================================================
# UI
# ============================================================

async def _edit_quiz_message(callback: CallbackQuery, *, text: str, reply_markup=None):
    try:
        await callback.message.edit_text(
            text,
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")


async def _show_question(callback: CallbackQuery, step: int):
    q = QUIZ[step]
    text = f"🧩 <b>Проф-тест трейдера</b>\n\n{html.escape(q.title)}"
    await _edit_quiz_message(
        callback,
        text=text,
        reply_markup=get_quiz_answer_inline_kb(q),
    )


# ============================================================
# HANDLERS
# ============================================================

@router.callback_query(F.data == "quiz:start")
async def quiz_start(callback: CallbackQuery):
    await callback.answer()
    tg_id = callback.from_user.id
    await _reset_quiz(tg_id)
    await _show_question(callback, 0)


@router.callback_query(F.data == "quiz:cancel")
async def quiz_cancel(callback: CallbackQuery):
    await callback.answer("Тест остановлен")
    await _edit_quiz_message(
        callback,
        text="Тест остановлен.\n\nЕсли захотите — нажмите кнопку ниже 👇",
        reply_markup=get_quiz_start_inline_kb(),
    )


@router.callback_query(F.data.startswith("quiz:answer:"))
async def quiz_answer(callback: CallbackQuery):
    await callback.answer()
    tg_id = callback.from_user.id

    _, _, q_key, value = callback.data.split(":", 3)

    step = await _save_answer(tg_id, q_key, value)

    if step < len(QUIZ):
        await _show_question(callback, step)
        return

    answers = await _load_answers_map(tg_id)
    rec = _recommendation(answers)

    await move_to_first_touch_if_needed(bitrix=bitrix_client, tg_id=tg_id)

    # Bitrix log
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
        if deal:
            await bitrix_client.add_deal_timeline_comment(
                deal["ID"],
                f"🧩 Тест пройден.\nTG_ID: {tg_id}\nРекомендация: {_rec_title(rec)}"
            )
    except Exception:
        pass

    # уведомление в админ/группу
    try:
        await notify_quiz_completed_no_phone(
            bot=callback.bot,
            tg_id=tg_id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
            level=_rec_title(rec),
            score=_manual_score(answers),
            gift=None,
        )
    except Exception:
        pass

    await _edit_quiz_message(
        callback,
        text=(
            "✅ <b>Тест завершён!</b>\n\n"
            f"По результатам вам больше подходит:\n<b>{_rec_title(rec)}</b>\n\n"
            "Выберите направление 👇"
        ),
        reply_markup=get_quiz_choice_inline_kb(recommended=rec),
    )


@router.callback_query(F.data.startswith("quiz:choice:"))
async def quiz_choice(callback: CallbackQuery):
    await callback.answer()
    tg_id = callback.from_user.id
    choice = callback.data.split(":")[-1]

    await _set_choice(tg_id, choice)
    await move_to_first_touch_if_needed(bitrix=bitrix_client, tg_id=tg_id)

    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
        if deal:
            await bitrix_client.add_deal_timeline_comment(
                deal["ID"],
                f"✅ Клиент выбрал формат: {choice}"
            )
    except Exception:
        pass

    await _edit_quiz_message(
        callback,
        text=(
            "✅ Спасибо за выбор!\n\n"
            "Менеджер свяжется с вами и отправит информацию "
            "по развитию в выбранном направлении."
        ),
        reply_markup=get_quiz_start_inline_kb(),
    )
