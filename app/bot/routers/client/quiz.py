# app/bot/routers/client/quiz.py
from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery
from sqlalchemy import select, func, delete, update

from app.db.session import async_session_maker
from app.db.models import QuizSession, QuizAnswer, TGUser
from app.bot.keyboards.quiz import (
    get_quiz_answer_inline_kb,
    get_quiz_start_inline_kb,
    get_quiz_choice_inline_kb,
)
from app.integrations.bitrix.client import BitrixClient
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed
from app.services.quiz_notify_service import (
    send_quiz_result_notification,
    send_quiz_choice_notification,
)
from app.services.user_service import get_or_create_tg_user  # ✅ твоя функция

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
    order = ["goal", "time", "experience", "money", "discipline"]
    lines: list[str] = []
    for k in order:
        if k in answers:
            lines.append(f"• {_pretty_answer_label(k)}: {_pretty_answer_value(k, answers[k])}")
    for k, v in answers.items():
        if k not in order:
            lines.append(f"• {_pretty_answer_label(k)}: {_pretty_answer_value(k, v)}")
    return "\n".join(lines)


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

    # небольшой вклад
    if ans.get("money") in {"100-300", "300-1000"}:
        score += 1

    if ans.get("discipline") == "ok":
        score += 1

    return score


def _recommendation(ans: dict[str, str]) -> str:
    return "manual" if _manual_score(ans) >= 6 else "robot"


def _rec_title(rec: str) -> str:
    return "🧑‍💻 Ручная торговля на Forex" if rec == "manual" else "🤖 Автоматическая торговля (роботы)"


# ============================================================
# DB HELPERS (FK-safe + idempotent)
# ============================================================

async def _ensure_user_and_session(tg_id: int, from_user) -> None:
    """
    Гарантирует:
      - tg_user существует (иначе FK на quiz_session упадёт)
      - quiz_session существует
    """
    async with async_session_maker() as session:
        await get_or_create_tg_user(session, from_user)  # ✅ flush внутри
        qs = await session.get(QuizSession, tg_id)
        if not qs:
            session.add(QuizSession(tg_id=tg_id, step=0, finished=False))
        await session.commit()


async def _reset_quiz(tg_id: int) -> None:
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        if not qs:
            # на всякий (если кто-то вызвал reset без ensure)
            session.add(QuizSession(tg_id=tg_id, step=0, finished=False))
            await session.flush()
            qs = await session.get(QuizSession, tg_id)

        qs.step = 0
        qs.finished = False
        qs.gift = None
        qs.phone = None
        qs.score = None
        qs.level = None
        qs.updated_at = datetime.utcnow()

        await session.execute(delete(QuizAnswer).where(QuizAnswer.tg_id == tg_id))
        await session.commit()


async def _save_answer_idempotent(tg_id: int, q_key: str, value: str) -> int:
    """
    Идемпотентно сохраняем ответ:
      - удаляем прежний ответ на этот вопрос (если был)
      - вставляем новый
      - возвращаем кол-во отвеченных вопросов
    Это убирает дубли при двойном клике.
    """
    async with async_session_maker() as session:
        await session.execute(
            delete(QuizAnswer).where(QuizAnswer.tg_id == tg_id, QuizAnswer.q_key == q_key)
        )
        session.add(QuizAnswer(tg_id=tg_id, q_key=q_key, answer=value))
        await session.flush()

        cnt = await session.scalar(
            select(func.count()).select_from(QuizAnswer).where(QuizAnswer.tg_id == tg_id)
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
            select(QuizAnswer.q_key, QuizAnswer.answer).where(QuizAnswer.tg_id == tg_id)
        )
        rows = res.all()
    return {k: v for k, v in rows}


async def _mark_user_quiz_completed(tg_id: int) -> None:
    async with async_session_maker() as session:
        res = await session.execute(select(TGUser).where(TGUser.tg_id == tg_id))
        user = res.scalar_one_or_none()
        if user:
            user.quiz_completed = True
            user.quiz_completed_at = datetime.utcnow()
            await session.commit()


async def _try_finalize_quiz_once(tg_id: int, score: int, level: str) -> bool:
    """
    Атомарная защита от дублей (последний ответ):
      - обновляем score/level только если score ещё NULL
    Возвращает True если это первый финалайз, False если уже было.
    """
    async with async_session_maker() as session:
        res = await session.execute(
            update(QuizSession)
            .where(QuizSession.tg_id == tg_id, QuizSession.score.is_(None))
            .values(
                score=score,
                level=level,
                finished=True,
                step=len(QUIZ),
                updated_at=datetime.utcnow(),
            )
        )
        await session.commit()
        return (res.rowcount or 0) > 0


async def _try_set_choice_once(tg_id: int, choice: str) -> bool:
    """
    Атомарная защита от дублей (manual/robot):
      - обновляем gift только если gift ещё NULL
    """
    async with async_session_maker() as session:
        res = await session.execute(
            update(QuizSession)
            .where(QuizSession.tg_id == tg_id, QuizSession.gift.is_(None))
            .values(
                gift=choice,
                finished=True,
                updated_at=datetime.utcnow(),
            )
        )
        await session.commit()
        return (res.rowcount or 0) > 0


# ============================================================
# UI
# ============================================================

async def _edit_quiz_message(callback: CallbackQuery, *, text: str, reply_markup=None):
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except TelegramBadRequest:
        await callback.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")


async def _show_question(callback: CallbackQuery, step: int):
    q = QUIZ[step]
    text = f"🧩 <b>Проф-тест трейдера:</b>\n\n{html.escape(q.title)}"
    await _edit_quiz_message(callback, text=text, reply_markup=get_quiz_answer_inline_kb(q))


# ============================================================
# HANDLERS
# ============================================================

@router.callback_query(F.data == "quiz:start")
async def quiz_start(callback: CallbackQuery):
    await callback.answer()
    if not callback.message:
        return

    tg_id = callback.from_user.id

    # ✅ FK-safe: пользователь мог прийти из рассылки после очистки БД
    await _ensure_user_and_session(tg_id, callback.from_user)
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
    if not callback.message:
        return

    tg_id = callback.from_user.id
    _, _, q_key, value = callback.data.split(":", 3)

    # ✅ идемпотентное сохранение ответа (перезапись при двойном клике)
    step = await _save_answer_idempotent(tg_id, q_key, value)

    # продолжаем тест
    if step < len(QUIZ):
        await _show_question(callback, step)
        return

    # ✅ мгновенно убираем кнопки последнего вопроса (защита от повторных тапов)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    # собираем ответы/скоринг
    answers = await _load_answers_map(tg_id)
    score = _manual_score(answers)
    rec = _recommendation(answers)
    level = _rec_title(rec)
    answers_text = _format_answers_for_comment(answers)

    # ✅ атомарная защита: финализируем тест только один раз
    first_finalize = await _try_finalize_quiz_once(tg_id, score=score, level=level)
    await _mark_user_quiz_completed(tg_id)

    # если уже финализировали ранее — просто покажем выбор направления и выйдем
    if not first_finalize:
        await _edit_quiz_message(
            callback,
            text=(
                "✅ <b>Тест завершён!</b>\n\n"
                f"По результатам вам больше подходит:\n<b>{level}</b>\n\n"
                "Выберите направление 👇"
            ),
            reply_markup=get_quiz_choice_inline_kb(recommended=rec),
        )
        return

    # Bitrix stage guard
    try:
        await move_to_first_touch_if_needed(bitrix=bitrix_client, tg_id=tg_id)
    except Exception:
        pass

    # 1) комментарий в Bitrix — 1 раз
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

    # 2) уведомление админам/в группу — 1 раз (включая ответы)
    try:
        await send_quiz_result_notification(
            bot=callback.bot,
            tg_id=tg_id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
            level=level,
            score=score,
            answers_text=answers_text,
        )
    except Exception:
        logger.exception("send_quiz_result_notification failed tg_id=%s", tg_id)

    # финальный экран (выбор направления)
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
    if not callback.message:
        return

    tg_id = callback.from_user.id
    choice = callback.data.split(":")[-1]

    # ✅ мгновенно убираем кнопки
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass

    # ✅ атомарно записываем выбор (idempotent)
    first_choice = await _try_set_choice_once(tg_id, choice)
    if not first_choice:
        # уже было — просто ответим клиенту (без повторных уведомлений)
        await _edit_quiz_message(
            callback,
            text=(
                "✅ Спасибо за выбор!\n\n"
                "Менеджер свяжется с вами и отправит информацию "
                "по развитию в выбранном направлении."
            ),
            reply_markup=get_quiz_start_inline_kb(),
        )
        return

    choice_map = {
        "manual": "🧑‍💻 Ручная торговля",
        "robot": "🤖 Автоматическая торговля (роботы)",
    }
    choice_text = choice_map.get(choice, choice)

    # Bitrix stage guard
    try:
        await move_to_first_touch_if_needed(bitrix=bitrix_client, tg_id=tg_id)
    except Exception:
        pass

    # Bitrix comment (1 раз)
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
        if deal:
            await bitrix_client.add_deal_timeline_comment(
                deal["ID"],
                f"✅ <b>Клиент выбрал направление:</b> {choice_text}",
            )
    except Exception:
        logger.exception("bitrix choice comment failed tg_id=%s", tg_id)

    # notify admins/group (1 раз)
    try:
        await send_quiz_choice_notification(
            bot=callback.bot,
            tg_id=tg_id,
            username=callback.from_user.username,
            full_name=callback.from_user.full_name,
            choice_text=choice_text,
        )
    except Exception:
        logger.exception("send_quiz_choice_notification failed tg_id=%s", tg_id)

    # ответ клиенту (ВАЖНО: через _edit_quiz_message, чтобы не упасть на edit_text edge-cases)
    await _edit_quiz_message(
        callback,
        text=(
            "✅ Спасибо за выбор!\n\n"
            "Менеджер свяжется с вами и отправит информацию "
            "по развитию в выбранном направлении."
        ),
    )