# app/bot/routers/client/result.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InputMediaVideo, InputMediaPhoto

from app.bot.keyboards.results import get_reviews_list_keyboard, get_review_keyboard
from app.config import (
    REVIEW_1_VIDEO_FILE_ID,
    REVIEW_2_VIDEO_FILE_ID,
    REVIEW_3_VIDEO_FILE_ID,
    REVIEW_4_VIDEO_FILE_ID, RESULTS_IMAGE_FILE_ID,
)

router = Router(name="client-results")

RESULTS_TEXT = (
    "📊 <b>Результаты — через честность</b>\n\n"
    "Здесь вы не увидите глянцевых «успешных историй» с актёрами и шаблонными фразами.\n"
    "❌ Никаких купленных отзывов\n"
    "❌ Никакого пафоса\n\n"

    "👤 Только живые люди.\n"
    "Те, кто прошёл путь:\n"
    "• от неуверенности — к осознанной торговле\n"
    "• от хаоса на графике — к чёткой системе\n"
    "• от страха убытков — к спокойному принятию риска\n\n"

    "🗣 <b>Эти отзывы — не ради пиара.</b>\n"
    "Их оставляют добровольно — чтобы помочь другим не тратить годы впустую.\n"
    "Потому что когда-то они сами стояли на этом пороге:\n"
    "с вопросами, сомнениями и надеждой, что <i>научиться возможно</i>.\n\n"

    "👇 Выберите отзыв — и услышьте реальный голос человека,\n"
    "который однажды решил разобраться в рынке по-настоящему.\n\n"

    "<i>Иногда самый ценный сигнал — не на графике,\n"
    "а в словах того, кто уже прошёл этот путь.</i> 💬✨"
)


def _review_text(n: int) -> str:
    texts = {

        1: (
            "🎥 <b>Отзыв 1</b>\n\n"
            "Отзыв ученика, который прошел обучение у <b>Антона Гана</b>."
        ),
        2: (
            "🎥 <b>Отзыв 2</b>\n\n"
            "Отзыв ученика, который прошел обучение у <b>Андрея Миклушевского</b>."
        ),
        3: (
            "🎥 <b>Отзыв 3</b>\n\n"
            "Отзыв ученика, который прошел обучение у <b>Антона Гана</b>\n"
            "и постоянно участвует в <b>онлайн-торговле</b>."
        ),
        4: (
            "🎥 <b>Отзыв 4</b>\n\n"
            "Ознакомьтесь с закрытым каналом <b>Sniper CLUB</b>,\n"
            "где в одном из топиков ученики делятся своими результатами."
        ),
    }
    return texts.get(n, "🎥 <b>Отзыв</b>")


def _get_review_video_file_id(n: int) -> str | None:
    return {

        1: REVIEW_2_VIDEO_FILE_ID,
        2: REVIEW_3_VIDEO_FILE_ID,
        3: REVIEW_4_VIDEO_FILE_ID,
        4: REVIEW_1_VIDEO_FILE_ID,
    }.get(n)


@router.message(F.text == "📊 Результаты")
async def results_entry(message: Message):
    # главное меню "Отзывы" = фото+текст (если есть), иначе текст
    if RESULTS_IMAGE_FILE_ID:
        await message.answer_photo(
            photo=RESULTS_IMAGE_FILE_ID,
            caption=RESULTS_TEXT,
            reply_markup=get_reviews_list_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            RESULTS_TEXT,
            reply_markup=get_reviews_list_keyboard(),
            parse_mode="HTML",
        )


@router.callback_query(F.data == "results:back")
async def results_back(callback: CallbackQuery):
    await callback.answer()

    # назад всегда возвращаемся на "картинка+текст" (если есть), иначе текст
    if RESULTS_IMAGE_FILE_ID:
        media = InputMediaPhoto(
            media=RESULTS_IMAGE_FILE_ID,
            caption=RESULTS_TEXT,
            parse_mode="HTML",
        )
        await callback.message.edit_media(
            media=media,
            reply_markup=get_reviews_list_keyboard(),
        )
    else:
        # если сейчас было видео, edit_text может упасть -> безопаснее удалить и отправить заново
        try:
            await callback.message.edit_text(
                RESULTS_TEXT,
                reply_markup=get_reviews_list_keyboard(),
                parse_mode="HTML",
            )
        except Exception:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                RESULTS_TEXT,
                reply_markup=get_reviews_list_keyboard(),
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("results:review:"))
async def open_review(callback: CallbackQuery):
    await callback.answer()

    try:
        n = int(callback.data.split(":")[-1])
    except Exception:
        # если текущее сообщение медиа — надо редактировать caption/media
        if callback.message and (callback.message.photo or callback.message.video):
            await callback.message.edit_caption(
                caption="Некорректный отзыв. Вернитесь назад.",
                reply_markup=get_review_keyboard(),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                "Некорректный отзыв. Вернитесь назад.",
                reply_markup=get_review_keyboard(),
                parse_mode="HTML",
            )
        return

    text = _review_text(n)
    video_id = _get_review_video_file_id(n)

    # Если видео нет — показываем просто текст (НО корректно по типу сообщения)
    if not video_id:
        if callback.message and (callback.message.photo or callback.message.video):
            await callback.message.edit_caption(
                caption=text,
                reply_markup=get_review_keyboard(),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                text,
                reply_markup=get_review_keyboard(),
                parse_mode="HTML",
            )
        return

    # Видео есть — всегда переводим сообщение в "video + caption"
    media = InputMediaVideo(
        media=video_id,
        caption=text,
        parse_mode="HTML",
    )
    await callback.message.edit_media(
        media=media,
        reply_markup=get_review_keyboard(),
    )
