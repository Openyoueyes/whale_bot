from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from datetime import datetime

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, func

from app.db.session import async_session_maker
from app.db.models import QuizSession, QuizAnswer, TGUser
from app.bot.keyboards.quiz import (
    get_quiz_answer_inline_kb,
    get_quiz_gift_inline_kb,
    get_share_contact_kb,
    get_quiz_start_inline_kb,
)
from app.integrations.bitrix.client import BitrixClient
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed
from app.services.quiz_notify_service import (
    notify_quiz_completed_no_phone,
    notify_quiz_phone_received,
)

logger = logging.getLogger(__name__)
router = Router(name="client-quiz")

bitrix_client = BitrixClient()


# ============================================================
# quiz content
# ============================================================

@dataclass(frozen=True)
class QuizQuestion:
    key: str
    title: str
    options: list[tuple[str, str]]  # (button_text, value)


QUIZ: list[QuizQuestion] = [
    QuizQuestion(
        key="exp",
        title="1️⃣ Сколько времени вы в трейдинге?",
        options=[
            ("0 — ещё не торговал(а)", "0"),
            ("до 3 месяцев", "1"),
            ("3–12 месяцев", "2"),
            ("1–3 года", "3"),
            ("3+ лет", "4"),
        ],
    ),
    QuizQuestion(
        key="market",
        title="2️⃣ Что вам интереснее всего?",
        options=[
            ("Forex", "fx"),
            ("Крипто", "crypto"),
            ("Индексы", "index"),
            ("Акции", "stocks"),
            ("Пока не знаю", "na"),
        ],
    ),
    QuizQuestion(
        key="risk",
        title="3️⃣ Какой риск на сделку вы обычно используете?",
        options=[
            ("Не знаю / не считал(а)", "na"),
            ("до 1%", "1"),
            ("1–2%", "2"),
            ("3–5%", "3"),
            ("Без стопов 😅", "nostop"),
        ],
    ),
    QuizQuestion(
        key="pain",
        title="4️⃣ Что сейчас больше всего мешает результату?",
        options=[
            ("Не понимаю, где входить", "entry"),
            ("Не хватает дисциплины", "disc"),
            ("Нет понятной системы", "system"),
            ("Психология/эмоции", "psy"),
            ("Хочу просто посмотреть как торгуют профи", "watch"),
        ],
    ),
]


# ============================================================
# scoring
# ============================================================

def _score_from_answers(ans: dict[str, str]) -> int:
    score = 0

    exp = ans.get("exp")
    if exp in {"0", "1"}:
        score += 0
    elif exp == "2":
        score += 1
    elif exp == "3":
        score += 2
    elif exp == "4":
        score += 3

    risk = ans.get("risk")
    if risk == "na":
        score += 0
    elif risk == "1":
        score += 2
    elif risk == "2":
        score += 3
    elif risk == "3":
        score += 2
    elif risk == "nostop":
        score += 0

    if ans.get("pain") in {"system", "disc", "entry"}:
        score += 1

    return score


def _level_from_score(score: int) -> str:
    if score <= 2:
        return "Новичок"
    if score <= 5:
        return "Уверенный уровень"
    return "Продвинутый"


def _gift_name(gift: str | None) -> str:
    if gift == "session":
        return "Онлайн-сессия"
    if gift == "consult":
        return "Консультация"
    return "не выбран"


# ============================================================
# Bitrix helpers
# ============================================================

async def _ensure_first_touch_if_bad_stage(tg_id: int) -> None:
    """
    Если сделка в отрицательной стадии — переносим в 1 касание.
    Важно: квиз работает через callback_query, middleware на message его не трогает.
    """
    try:
        await move_to_first_touch_if_needed(bitrix=bitrix_client, tg_id=tg_id)
    except Exception:
        logger.exception("ensure_first_touch failed tg_id=%s", tg_id)


async def _get_deal_id_for_tg(tg_id: int) -> str | None:
    """
    Находим сделку:
    1) по UF TG_ID в сделках
    2) fallback: через lead (по TG_ID) -> deal по LEAD_ID
    """
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        deal = None

    if deal and deal.get("ID"):
        return str(deal["ID"])

    try:
        leads = await bitrix_client.list_leads_by_telegram_id(tg_id)
    except Exception:
        leads = []

    if not leads:
        return None

    try:
        lead_id = int(sorted(leads, key=lambda x: int(x["ID"]))[0]["ID"])
    except Exception:
        return None

    try:
        deals = await bitrix_client.list_deals_by_lead_id(lead_id)
    except Exception:
        deals = []

    if deals:
        return str(deals[0]["ID"])
    return None


async def _bitrix_log_quiz_result(
        tg_id: int,
        answers: dict[str, str],
        score: int,
        level: str,
) -> None:
    deal_id = await _get_deal_id_for_tg(tg_id)
    if not deal_id:
        return

    lines = [
        "🧩 Клиент прошёл квиз в Telegram боте.",
        f"TG_ID: {tg_id}",
        "",
        "📌 Ответы:",
        f"— exp: {answers.get('exp', '-')}",
        f"— market: {answers.get('market', '-')}",
        f"— risk: {answers.get('risk', '-')}",
        f"— pain: {answers.get('pain', '-')}",
        "",
        f"🎯 Результат: {level} (score={score})",
        "📞 Контакт: ещё не оставлен",
    ]
    try:
        await bitrix_client.add_deal_timeline_comment(deal_id, "\n".join(lines))
    except Exception:
        pass


async def _bitrix_log_gift_selected(tg_id: int, gift: str) -> None:
    deal_id = await _get_deal_id_for_tg(tg_id)
    if not deal_id:
        return

    text = (
        "🎁 Клиент выбрал подарок в квизе.\n"
        f"TG_ID: {tg_id}\n"
        f"Подарок: {_gift_name(gift)}"
    )
    try:
        await bitrix_client.add_deal_timeline_comment(deal_id, text)
    except Exception:
        pass


async def _bitrix_log_phone_received(tg_id: int, phone: str, level: str, score: int, gift: str | None) -> None:
    deal_id = await _get_deal_id_for_tg(tg_id)
    if not deal_id:
        return

    text = (
        "📞 Клиент оставил контакт после квиза.\n"
        f"TG_ID: {tg_id}\n"
        f"Телефон: {phone}\n"
        f"Уровень: {level} (score={score})\n"
        f"Подарок: {_gift_name(gift)}"
    )
    try:
        await bitrix_client.add_deal_timeline_comment(deal_id, text)
    except Exception:
        pass


# ============================================================
# db primitives
# ============================================================

async def _get_or_create_session(tg_id: int) -> QuizSession:
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        if not qs:
            qs = QuizSession(tg_id=tg_id, step=0, finished=False)
            session.add(qs)
            await session.commit()
        return qs


async def _save_answer(tg_id: int, q_key: str, value: str) -> int:
    async with async_session_maker() as session:
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
            QuizAnswer.__table__.select()
            .where(QuizAnswer.tg_id == tg_id)
            .order_by(QuizAnswer.created_at.asc())
        )
        rows = res.mappings().all()

    out: dict[str, str] = {}
    for r in rows:
        out[str(r["q_key"])] = str(r["answer"])
    return out


async def _set_gift(tg_id: int, gift: str) -> None:
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        if not qs:
            qs = QuizSession(tg_id=tg_id, step=0, finished=False)
            session.add(qs)

        qs.gift = gift
        qs.updated_at = datetime.utcnow()
        await session.commit()


async def _set_result_if_exists(tg_id: int, level: str, score: int) -> None:
    """
    На момент завершения квиза (без телефона) — сохраняем score/level в QuizSession
    """
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        if not qs:
            qs = QuizSession(tg_id=tg_id, step=len(QUIZ), finished=False)
            session.add(qs)

        qs.level = level
        qs.score = score
        qs.updated_at = datetime.utcnow()
        await session.commit()


async def _set_phone_and_finish(tg_id: int, phone: str, level: str, score: int) -> None:
    phone = phone.strip()

    gift: str | None = None

    async with async_session_maker() as session:
        try:
            qs = await session.get(QuizSession, tg_id)
            if not qs:
                qs = QuizSession(tg_id=tg_id, step=len(QUIZ), finished=False)
                session.add(qs)

            gift = qs.gift

            qs.phone = phone
            qs.level = level
            qs.score = score
            qs.finished = True
            qs.updated_at = datetime.utcnow()

            tg_user = await session.scalar(select(TGUser).where(TGUser.tg_id == tg_id))
            if tg_user:
                tg_user.tg_phone = phone
                tg_user.quiz_completed = True
                tg_user.quiz_completed_at = datetime.utcnow()

            await session.commit()

        except Exception:
            await session.rollback()
            logger.exception("Quiz phone save failed tg_id=%s phone=%s", tg_id, phone)
            raise

    # Bitrix: обновляем телефон в сделке (как у тебя было)
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)

        if not deal:
            leads = await bitrix_client.list_leads_by_telegram_id(tg_id)
            if leads:
                lead_id = int(sorted(leads, key=lambda x: int(x["ID"]))[0]["ID"])
                deals = await bitrix_client.list_deals_by_lead_id(lead_id)
                if deals:
                    deal = {"ID": deals[0]["ID"]}

        if deal:
            await bitrix_client.update_deal_phone(deal_id=deal["ID"], phone=phone)
        else:
            logger.warning("Bitrix deal not found for phone update tg_id=%s", tg_id)

    except Exception:
        logger.exception("Bitrix phone update failed tg_id=%s phone=%s", tg_id, phone)

    # Bitrix timeline: телефон + уровень + подарок
    try:
        await _bitrix_log_phone_received(tg_id, phone, level, score, gift)
    except Exception:
        pass

    # Уведомление в группу (второе) — телефон получен
    try:
        await notify_quiz_phone_received(tg_id=tg_id, phone=phone, level=level, score=score)
    except Exception:
        pass


async def _reset_quiz(tg_id: int) -> None:
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        if qs:
            qs.step = 0
            qs.finished = False
            qs.phone = None
            qs.gift = None
            qs.level = None
            qs.score = None
            qs.updated_at = datetime.utcnow()

        await session.execute(QuizAnswer.__table__.delete().where(QuizAnswer.tg_id == tg_id))
        await session.commit()


async def _get_session_gift(tg_id: int) -> str | None:
    async with async_session_maker() as session:
        qs = await session.get(QuizSession, tg_id)
        return qs.gift if qs else None


# ============================================================
# ui helpers (text vs caption)
# ============================================================

async def _edit_quiz_message(callback: CallbackQuery, *, text: str, reply_markup=None) -> None:
    """
    FIX: если сообщение с видео/фото — редактируем caption.
    """
    if not callback.message:
        return

    try:
        if (
                callback.message.video
                or callback.message.photo
                or callback.message.document
                or callback.message.animation
                or callback.message.audio
        ):
            await callback.message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML",
            )
    except TelegramBadRequest as e:
        if "can't parse entities" in str(e).lower():
            plain = text.replace("<b>", "").replace("</b>", "")
            try:
                await callback.message.answer(plain, reply_markup=reply_markup)
                return
            except Exception:
                return

        # fallback: отправляем новое сообщение
        try:
            await callback.message.answer(text, reply_markup=reply_markup, parse_mode="HTML")
        except Exception:
            return


async def _show_question(callback: CallbackQuery, step: int) -> None:
    q = QUIZ[step]
    safe_title = html.escape(q.title)
    text = f"🧩 <b>Тест: уровень трейдера</b>\n\n{safe_title}\n\nВыберите вариант:"
    await _edit_quiz_message(
        callback,
        text=text,
        reply_markup=get_quiz_answer_inline_kb(q.key, q.options),
    )


# ============================================================
# handlers
# ============================================================

@router.callback_query(F.data == "quiz:start")
async def quiz_start(callback: CallbackQuery):
    await callback.answer()

    tg_id = callback.from_user.id
    await _reset_quiz(tg_id)
    await _get_or_create_session(tg_id)

    await _show_question(callback, 0)


@router.callback_query(F.data == "quiz:cancel")
async def quiz_cancel(callback: CallbackQuery):
    await callback.answer("Тест остановлен")
    await _reset_quiz(callback.from_user.id)

    await _edit_quiz_message(
        callback,
        text="Ок, тест остановлен.\n\nЕсли захотите — нажмите кнопку ниже 👇",
        reply_markup=get_quiz_start_inline_kb(),
    )


@router.callback_query(F.data.startswith("quiz:a:"))
async def quiz_answer(callback: CallbackQuery):
    await callback.answer()
    if not callback.message:
        return

    tg_id = callback.from_user.id

    try:
        _, _, q_key, value = (callback.data or "").split(":", 3)
    except Exception:
        return

    step = await _save_answer(tg_id, q_key, value)

    if step < len(QUIZ):
        await _show_question(callback, step)
        return

    answers = await _load_answers_map(tg_id)
    score = _score_from_answers(answers)
    level = _level_from_score(score)
    await _ensure_first_touch_if_bad_stage(tg_id)
    await notify_quiz_completed_no_phone(
        bot=callback.bot,
        tg_id=tg_id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
        level=level,
        score=score,
        gift=None,  # подарок ещё не выбран на этом шаге
    )
    await _set_result_if_exists(tg_id, level, score)

    # Bitrix: ответы + результат
    try:
        await _bitrix_log_quiz_result(tg_id, answers, score, level)
    except Exception:
        pass

    # Уведомление в группу №1: прошёл квиз, телефона нет
    try:
        await notify_quiz_completed_no_phone(tg_id=tg_id, level=level, score=score)
    except Exception:
        pass

    text = (
        "✅ <b>Готово!</b>\n\n"
        f"Ваш уровень: <b>{level}</b> 🎯\n\n"
        "🎁 Выберите подарок, который хотите забрать:"
    )
    await _edit_quiz_message(callback, text=text, reply_markup=get_quiz_gift_inline_kb())


@router.callback_query(F.data.startswith("quiz:gift:"))
async def quiz_gift(callback: CallbackQuery):
    await callback.answer()
    if not callback.message:
        return

    tg_id = callback.from_user.id
    gift = (callback.data or "").split(":")[-1]
    await _set_gift(tg_id, gift)
    await _ensure_first_touch_if_bad_stage(tg_id)
    # Bitrix: выбран подарок
    try:
        await _bitrix_log_gift_selected(tg_id, gift)
    except Exception:
        pass

    gift_name = "Онлайн-сессия" if gift == "session" else "Консультация"
    text = (
        f"🎁 Вы выбрали: <b>{gift_name}</b>\n\n"
        "Чтобы закрепить подарок — отправьте номер телефона одной кнопкой ниже 👇"
    )
    await callback.message.answer(text, reply_markup=get_share_contact_kb(), parse_mode="HTML")


@router.message(F.contact)
async def quiz_contact(message: Message):
    tg_id = message.from_user.id if message.from_user else None
    if not tg_id:
        return
    await _ensure_first_touch_if_bad_stage(tg_id)
    phone = (message.contact.phone_number or "").strip()
    if not phone:
        await message.answer("Не вижу телефон 😔 Попробуйте ещё раз кнопкой «Поделиться телефоном».")
        return

    answers = await _load_answers_map(tg_id)
    score = _score_from_answers(answers)
    level = _level_from_score(score)

    await _set_phone_and_finish(tg_id, phone, level, score)

    # достаём выбранный подарок
    gift = await _get_session_gift(tg_id)

    # 2) Уведомление в группу: телефон получен
    try:
        await notify_quiz_phone_received(
            bot=message.bot,
            tg_id=tg_id,
            username=message.from_user.username if message.from_user else None,
            full_name=message.from_user.full_name if message.from_user else "Без имени",
            phone=phone,
            level=level,
            score=score,
            gift=gift,
        )
    except Exception:
        logger.exception("notify_quiz_phone_received failed")

    # убрать reply-клавиатуру
    from aiogram.types import ReplyKeyboardRemove
    await message.answer(
        "✅ Спасибо! Телефон получен.\n\n"
        "Менеджер свяжется с вами в ближайшее время.",
        reply_markup=ReplyKeyboardRemove(),
    )