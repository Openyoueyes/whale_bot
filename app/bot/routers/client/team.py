# app/bot/routers/client/team.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaVideo, InputMediaPhoto

from app.bot.keyboards.team import get_team_list_keyboard, get_team_profile_keyboard
from app.config import (
    TEAM_ANDREY_VIDEO_FILE_ID,
    TEAM_ANTON_VIDEO_FILE_ID,
    ANTON_RESULT_1_URL,
    ANTON_RESULT_2_URL, TEAM_IMAGE_FILE_ID, ANDREY_RESULT_1_URL, ANDREY_RESULT_2_URL, ANDREY_RESULT_3_URL,
)
from app.services.team_service import create_training_request

router = Router(name="client-team")

TEAM_LIST_TEXT = (
    "👥 <b>Команда SNIPER CLUB</b>\n\n"
    "Мы — трейдеры-практики, которые ежедневно работают с реальным рынком.\n"
    "Без «воды» и теории ради теории — только живая торговля, дисциплина и системный подход.\n\n"
    "📈 <b>Более 62 лет суммарного опыта</b>\n"
    "Каждый из нас прошёл свой путь: убытки, прорывы, сотни сделок и тысячи часов у графиков.\n"
    "И теперь мы делимся этим с вами — честно и по-деловому.\n\n"
    "👇 Выберите специалиста, чтобы узнать подробнее о его подходе, стиле и опыте.\n\n"
    "Рядом с профессионалами — расти легче. 💪"
)


def _andrey_caption() -> str:
    return (
        "<b>Андрей Миклушевский</b>\n"
        "Основатель торговой системы <b>Sniper</b>\n\n"
        "• Опыт: <b>12 лет</b> в реальной торговле\n"
        "• Рынки: <b>Forex, фондовый рынок</b>\n"
        "• Стратегия: <b>Sniper</b>\n"
        "• Обучил учеников: <b>более 10 000 трейдеров</b>\n\n"
        "Андрей специализируется на сценарном анализе рынка,\n"
        "поиске точек входа с коротким стопом и высоким соотношением риск/прибыль.\n"
        "Работает только с подтверждённой рыночной логикой.\n\n"
        "<b>📊 Реальные торговые мониторинги:</b>\n"
        "• <a href=\"https://www.myfxbook.com/members/AcademyFXRU/andrey-miklusheyski/10852350\">Myfxbook — Андрей Миклушевский</a>\n"
        "• <a href=\"https://www.myfxbook.com/members/AcademyFXRU/academyfx/3584064\">Myfxbook — AcademyFX</a>\n"
        f"• <a href=\"{ANDREY_RESULT_1_URL}\">Результат трейдера №1</a>\n"
        f"• <a href=\"{ANDREY_RESULT_2_URL}\">Результат трейдера №2</a>\n"
        f"• <a href=\"{ANDREY_RESULT_3_URL}\">Результат трейдера №3</a>"
    )


def _anton_caption() -> str:
    return (
        "<b>Антон Ган</b>\n"
        "Трейдер-наставник Sniper Club\n\n"
        "• Опыт: <b>10 лет</b> в реальной торговле\n"
        "• Рынки: <b>Forex, фондовый рынок</b>\n"
        "• Стратегия: <b>Sniper</b>\n"
        "• Обучил учеников: <b>более 5 000 трейдеров</b>\n\n"
        "Антон делает упор на практику, дисциплину и работу\n"
        "с психологией трейдера. Помогает перейти от хаотичных\n"
        "сделок к системной и осознанной торговле.\n\n"
        "<b>📊 Примеры реальных результатов:</b>\n"
        f"• <a href=\"{ANTON_RESULT_1_URL}\">Результат трейдера №1</a>\n"
        f"• <a href=\"{ANTON_RESULT_2_URL}\">Результат трейдера №2</a>\n\n"
        "Нажмите кнопку ниже, чтобы оставить заявку на обучение."
    )


@router.message(F.text == "👥 Команда")
async def team_entry(message: Message):
    if TEAM_IMAGE_FILE_ID:
        await message.answer_photo(
            photo=TEAM_IMAGE_FILE_ID,
            caption=TEAM_LIST_TEXT,
            reply_markup=get_team_list_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            TEAM_LIST_TEXT,
            reply_markup=get_team_list_keyboard(),
            parse_mode="HTML",
        )

TEAM_LIST_VIDEO_FILE_ID = None


@router.callback_query(F.data == "team:back")
async def team_back(callback: CallbackQuery):
    await callback.answer()

    # Хотим вернуться к "фото + caption" как в team_entry
    if TEAM_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=TEAM_IMAGE_FILE_ID,
            caption=TEAM_LIST_TEXT,
            parse_mode="HTML",
        )

        # Если текущее сообщение было видео или фото — можно безопасно edit_media
        if callback.message and (callback.message.video or callback.message.photo):
            await callback.message.edit_media(
                media=media,
                reply_markup=get_team_list_keyboard(),
            )
            return

        # Если текущее сообщение было текстом (или неизвестный тип) — проще переслать заново
        if callback.message:
            try:
                await callback.message.delete()
            except Exception:
                pass

        await callback.message.answer_photo(
            photo=TEAM_IMAGE_FILE_ID,
            caption=TEAM_LIST_TEXT,
            reply_markup=get_team_list_keyboard(),
            parse_mode="HTML",
        )
        return

    # fallback: если фото нет, то просто текст
    await callback.message.edit_text(
        TEAM_LIST_TEXT,
        reply_markup=get_team_list_keyboard(),
        parse_mode="HTML",
    )

@router.callback_query(F.data == "team:andrey")
async def team_andrey(callback: CallbackQuery):
    await callback.answer()

    if TEAM_ANDREY_VIDEO_FILE_ID:
        media = InputMediaVideo(
            media=TEAM_ANDREY_VIDEO_FILE_ID,
            caption=_andrey_caption(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_team_profile_keyboard("andrey"),
        )
    else:
        await callback.message.edit_text(
            _andrey_caption(),
            reply_markup=get_team_profile_keyboard("andrey"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "team:anton")
async def team_anton(callback: CallbackQuery):
    await callback.answer()

    # 1. Редактируем текущее сообщение (текст / видео)
    if TEAM_ANTON_VIDEO_FILE_ID:
        media = InputMediaVideo(
            media=TEAM_ANTON_VIDEO_FILE_ID,
            caption=_anton_caption(),
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_team_profile_keyboard("anton"),
        )
    else:
        await callback.message.edit_text(
            _anton_caption(),
            reply_markup=get_team_profile_keyboard("anton"),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "team:anton:apply")
async def team_anton_apply(callback: CallbackQuery):
    await callback.answer()

    await create_training_request(
        bot=callback.bot,
        tg_user=callback.from_user,
        source="Команда / Антон Ган / Обучение",
    )

    confirm_text = (
        "✅ <b>Заявка принята</b>\n\n"
        "Менеджер свяжется с вами в ближайшее время."
    )

    # Если текущее сообщение с видео — меняем caption
    if callback.message and callback.message.video:
        await callback.message.edit_caption(
            caption=confirm_text,
            reply_markup=get_team_profile_keyboard("anton"),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            confirm_text,
            reply_markup=get_team_profile_keyboard("anton"),
            parse_mode="HTML",
        )
