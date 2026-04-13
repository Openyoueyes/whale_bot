# app/bot/routers/client/prem.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery, InputMediaPhoto

from app.bot.keyboards.prem import get_prem_list_keyboard, get_prem_post_apply_keyboard
from app.bot.keyboards.robots import get_robot_post_apply_keyboard
from app.bot.routers.client.robots import safe_edit_text_or_caption, safe_callback_answer
from app.config import PREM_IMAGE_FILE_ID
from app.integrations.bitrix.client import BitrixClient
from app.services.auto_followup_service import mark_activity
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed
from app.services.prem_service import create_prem_request

router = Router(name="client-prem")
bitrix_client = BitrixClient()

PREM_LIST_TEXT = (
    "🔥 <b>WhaleTrade Premium — система профессиональной торговли на Forex</b>\n\n"
    "Это не просто сигналы. Это структурированный подход, сопровождение и прозрачные результаты.\n\n"
    "🚀 <b>До 5 торговых сигналов ежедневно</b>\n"
    "Точки входа с понятной логикой и чёткими ориентирами.\n\n"
    "📊 <b>Профессиональные инструменты</b>\n"
    "Авторские индикаторы и современные системы анализа рынка.\n\n"
    "🎯 <b>Полное сопровождение сделок</b>\n"
    "Наша команда ведёт позиции от входа до фиксации результата.\n\n"
    "⚡️ <b>Оперативные уведомления</b>\n"
    "Реакция на внезапные и высокопотенциальные рыночные события.\n\n"
    "📈 <b>Открытые результаты торговли</b>\n"
    "Прозрачная статистика и реальные отчёты без скрытых цифр.\n\n"
    "💎 <b>Есть возможность бесплатного доступа в Premium-канал.</b>\n\n"
    "Нажмите кнопку получить доступ, чтобы узнать подрбности:"
)


@router.message(F.text == "💰 Whale Профит")
async def team_entry(message: Message):
    if PREM_IMAGE_FILE_ID:
        await message.answer_photo(
            photo=PREM_IMAGE_FILE_ID,
            caption=PREM_LIST_TEXT,
            reply_markup=get_prem_list_keyboard(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            PREM_LIST_TEXT,
            reply_markup=get_prem_list_keyboard(),
            parse_mode="HTML",
        )


TEAM_LIST_VIDEO_FILE_ID = None


@router.callback_query(F.data == "prem:apply")
async def team_anton_apply(callback: CallbackQuery):
    await callback.answer()

    await create_prem_request(
        bot=callback.bot,
        tg_user=callback.from_user,
        source="Премиум / Заявка / Кнопка в боте",
    )

    try:
        await mark_activity(callback.from_user.id)
    except Exception:
        pass
    # ✅ реакция на заявку: если клиент был в “плохих” стадиях — перекидываем в “1 касание”
    try:
        await move_to_first_touch_if_needed(bitrix_client, callback.from_user.id)
    except Exception:
        pass
    await safe_edit_text_or_caption(
        callback,
        text=(
            "✅✅✅ <b>Заявка принята</b>\n\n"
            "📩 Менеджер свяжется с вами в ближайшее время и расскажет подробнее про формат сотрудничества.\n\n"

        ),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "prem:back")
async def products_back(callback: CallbackQuery):
    await safe_callback_answer(callback)

    if not callback.message:
        return

    # Возвращаемся в список: желательно всегда с фото (если есть file_id)
    if PREM_IMAGE_FILE_ID:
        try:
            media = InputMediaPhoto(
                media=PREM_IMAGE_FILE_ID,
                caption=PREM_LIST_TEXT,
                parse_mode="HTML",
            )
            await callback.message.edit_media(
                media=media,
                reply_markup=get_prem_list_keyboard(),
            )
        except TelegramBadRequest:
            # если вдруг текущее сообщение не позволяет edit_media — отправим новое
            await callback.message.answer_photo(
                photo=PREM_IMAGE_FILE_ID,
                caption=PREM_LIST_TEXT,
                reply_markup=get_prem_list_keyboard(),
                parse_mode="HTML",
            )
    else:
        await safe_edit_text_or_caption(
            callback,
            text=PREM_IMAGE_FILE_ID,
            reply_markup=get_prem_list_keyboard(),
            parse_mode="HTML",
        )