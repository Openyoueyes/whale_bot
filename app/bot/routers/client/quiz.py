# app/bot/routers/client/quiz.py
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
from app.db.models import QuizSession, QuizAnswer, TGUser
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
            ("🤖 Запустить готовый алгоритм", "fast"),
            ("📚 Научиться торговать самому", "learn"),
        ],
    ),
    QuizQuestion(
        key="time",
        title="2️⃣ Сколько времени вы готовы уделять трейдингу в день?",
        options=[
            ("⏱ 10–20 минут", "10"),
            ("⏳ 30–60 минут", "30"),
            ("🕒 1–2 часа", "60"),
            ("🔥 2+ часа", "120"),
        ],
    ),
    QuizQuestion(
        key="experience",
        title="3️⃣ Ваш опыт на рынке Forex?",
        options=[
            ("🆕 Не торговал(а)", "0"),
            ("📉 До 3 месяцев", "1"),
            ("📈 3–12 месяцев", "2"),
            ("🏆 Более 1 года", "3"),
        ],
    ),
    QuizQuestion(
        key="money",
        title="4️⃣ Какой доход в месяц для вас приемлемый?",
        options=[
            ("✅ 100–300$", "100-300"),
            ("✅ 300–1000$", "300-1000"),
            ("✅ 1000$+", "1000+"),
        ],
    ),
    QuizQuestion(
        key="discipline",
        title="5️⃣ Как у вас с дисциплиной?",
        options=[
            ("😅 Эмоции мешают", "hard"),
            ("🧠 Работаю по системе", "ok"),
        ],
    ),
]


# ============================================================
# PRESENTATION HELPERS
# ============================================================

def _pretty_answer_label(key: str) -> str:
    mapping = {
        "goal": "Цель",
        "time": "Время в день",
        "experience": "Опыт",
        "money": "Желаемый доход",
        "discipline": "Дисциплина",
    }
    return mapping.get(key, key)


def _pretty_answer_value(key: str, value: str) -> str:
    # Можно расширять при необходимости
    if key == "goal":
        return {"fast": "Запустить готовый алгоритм", "learn": "Научиться торговать самому"}.get(value, value)
    if key == "time":
        return {"10": "10–20 минут", "30": "30–60 минут", "60": "1–2 часа", "120": "2+ часа"}.get(value, value)
    if key == "experience":
        return {"0": "Не торговал(а)", "1": "До 3 месяцев", "2": "3–12 месяцев", "3": "Более 1 года"}.get(value, value)
    if key == "money":
        return {"100-300": "100–300$", "300-1000": "300–1000$", "1000+": "1000$+"}.get(value, value)
    if key == "discipline":
        return {"hard": "Эмоции мешают", "ok": "Работаю по системе"}.get(value, value)
    return value


def _format_answers_for_comment(answers: dict[str, str]) -> str:
    # Выводим в заданном порядке, чтобы было красиво
    order = ["goal", "time", "experience", "money", "discipline"]
    lines: list[str] = []
    for k in order:
        if k in answers:
            lines.append(f"• {_pretty_answer_label(k)}: {_pretty_answer_value(k, answers[k])}")
    # На случай если появятся новые ключи
    for k, v in answers.items():
        if k not in order:
            lines.append(f"• {_pretty_answer_label(k)}: {_pretty_answer_value(k, v)}")
    return "\n".join(lines)


# ============================================================
# SCORING
# ============================================================

def _manual_score(ans: dict[str, str]) -> int:
    """
    Условная оценка "готов к ручной торговле".
    Чем выше — тем больше вероятность, что человеку зайдёт ручной формат.
    """
    score = 0

    # хочет учиться — плюс в "manual"
    if ans.get("goal") == "learn":
        score += 2

    # больше времени — плюс
    if ans.get("time") in {"60", "120"}:
        score += 2
    elif ans.get("time") == "30":
        score += 1

    # опыт — плюс
    if ans.get("experience") in {"2", "3"}:
        score += 2
    elif ans.get("experience") == "1":
        score += 1

    # доход: чем выше ожидания — тем чаще человеку ближе "системность/роботы",
    # но в реальности бывает наоборот. Дадим небольшой плюс "manual" только за средние ожидания.
    if ans.get("money") == "300-1000":
        score += 1
    elif ans.get("money") == "1000+":
        score += 0
    else:  # 100-300
        score += 1

    # дисциплина — критично для manual
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
            qs.phone = None
            qs.score = None
            qs.level = None
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


async def _mark_user_quiz_completed(tg_id: int) -> None:
    async with async_session_maker() as session:
        res = await session.execute(select(TGUser).where(TGUser.tg_id == tg_id))
        user = res.scalar_one_or_none()
        if user:
            user.quiz_completed = True
            user.quiz_completed_at = datetime.utcnow()
            await session.commit()


async def _save_quiz_summary(tg_id: int, *, score: int, level: str) -> None:
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        if qs:
            qs.score = score
            qs.level = level
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
    text = f"🧩 <b>Проф-тест трейдера:</b>\n\n{html.escape(q.title)}"
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

    # продолжаем тест
    if step < len(QUIZ):
        await _show_question(callback, step)
        return

    # тест завершён: собираем ответы/скоринг
    answers = await _load_answers_map(tg_id)
    score = _manual_score(answers)
    rec = _recommendation(answers)
    level = _rec_title(rec)

    # сохраняем агрегаты
    await _save_quiz_summary(tg_id, score=score, level=level)
    await _mark_user_quiz_completed(tg_id)

    # двигаем стадию в bitrix при необходимости
    await move_to_first_touch_if_needed(bitrix=bitrix_client, tg_id=tg_id)

    # красивый текст ответов
    answers_text = _format_answers_for_comment(answers)

    # комментарий в Bitrix (структурировано)
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
        if deal:
            await bitrix_client.add_deal_timeline_comment(
                deal["ID"],
                (
                    "🧩 <b>Тест пройден</b>\n"
                    "--------------------------------\n"
                    f"TG_ID: {tg_id}\n"
                    f"Уровень: {level}\n"
                    f"Score: {score}\n\n"
                    "<b>Ответы:</b>\n"
                    f"{answers_text}"
                ),
            )
    except Exception:
        logger.exception("bitrix comment failed tg_id=%s", tg_id)

    # уведомление в группу/админам:
    # 1) стандартный notify (как у тебя уже заведено)
    try:
        await notify_quiz_completed_no_phone(
            bot=callback.bot,
            tg_id=tg_id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
            level=level,
            score=score,
            gift=None,
        )
    except Exception:
        logger.exception("notify_quiz_completed_no_phone failed tg_id=%s", tg_id)

    # 2) ДОП: полный разбор с ответами — в группу/админам отдельным сообщением
    # (чтобы твой существующий notify не ломать)
    try:
        text_full = (
            "🧩 <b>Разбор ответов теста</b>\n"
            "----------------------------------------\n"
            f"<b>TG ID:</b> <code>{tg_id}</code>\n"
            f"<b>Username:</b> @{callback.from_user.username or 'нет'}\n"
            f"<b>Имя:</b> {html.escape(callback.from_user.full_name)}\n\n"
            f"<b>Уровень:</b> {level}\n"
            f"<b>Score:</b> {score}\n\n"
            f"<b>Ответы:</b>\n{answers_text}"
        )
        # отправляем админу(ам) — так уже есть в notify, но там без ответов.
        # Если хочешь только в группу — скажи, уберу админов.
        from app.config import ADMIN_IDS, GROUP_CHAT_MESSAGES_BOT_ID

        for admin_id in ADMIN_IDS:
            try:
                await callback.bot.send_message(admin_id, text_full, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass

        if GROUP_CHAT_MESSAGES_BOT_ID:
            try:
                await callback.bot.send_message(GROUP_CHAT_MESSAGES_BOT_ID, text_full, parse_mode="HTML", disable_web_page_preview=True)
            except Exception:
                pass
    except Exception:
        logger.exception("full quiz breakdown send failed tg_id=%s", tg_id)

    # финальный экран
    await _edit_quiz_message(
        callback,
        text=(
            "✅ <b>Тест завершён!</b>\n\n"
            f"По результатам вам больше подходит:\n<b>{level}</b>\n\n"
            "Выберите направление 👇"
        ),
        reply_markup=get_quiz_choice_inline_kb(recommended=rec),
    )


@router.callback_query(F.data.startswith("quiz:choice:"))
async def quiz_choice(callback: CallbackQuery):
    await callback.answer()

    tg_id = callback.from_user.id
    choice = callback.data.split(":")[-1]

    # 1️⃣ Сразу убираем кнопки (мгновенная защита от повторных кликов)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    # 2️⃣ Проверяем и сохраняем выбор атомарно
    async with async_session_maker() as session:

        qs = await session.get(QuizSession, tg_id)

        if not qs:
            return

        # если уже выбран — значит это повторный клик
        if qs.gift is not None:
            return

        qs.gift = choice
        qs.finished = True
        qs.updated_at = datetime.utcnow()

        await session.commit()

    # 3️⃣ Bitrix логика
    await move_to_first_touch_if_needed(bitrix=bitrix_client, tg_id=tg_id)

    choice_map = {
        "manual": "🧑‍💻 Ручная торговля",
        "robot": "🤖 Автоматическая торговля (роботы)",
        "consult": "☎️ Консультация",
        "session": "🎥 Разбор/сессия",
    }

    choice_text = choice_map.get(choice, choice)

    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)

        if deal:
            await bitrix_client.add_deal_timeline_comment(
                deal["ID"],
                f"✅ <b>Клиент выбрал направление:</b> {choice_text}",
            )

    except Exception:
        logger.exception("bitrix choice comment failed tg_id=%s", tg_id)

    # финальное сообщение
    await _edit_quiz_message(
        callback,
        text=(
            "✅ Спасибо за выбор!\n\n"
            "Менеджер свяжется с вами и отправит информацию "
            "по развитию в выбранном направлении."
        ),
        reply_markup=get_quiz_start_inline_kb(),
    )