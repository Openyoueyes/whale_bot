# app/bot/routers/client/prem.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message, CallbackQuery

from app.bot.keyboards.prem import get_prem_list_keyboard
from app.config import PREM_IMAGE_FILE_ID
from app.services.prem_service import create_prem_request

router = Router(name="client-prem")

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

    confirm_text = (
        "✅ <b>Спасибо за интерес!</b>\n\n"
        "Менеджер свяжется с вами в ближайшее время."
    )

    if not callback.message:
        return

    try:
        # если сообщение с фото или видео — редактируем caption
        if callback.message.photo or callback.message.video:
            await callback.message.edit_caption(
                caption=confirm_text,
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(
                confirm_text,
                parse_mode="HTML",
            )
    except TelegramBadRequest:
        # fallback — отправляем новое сообщение
        await callback.message.answer(
            confirm_text,
            parse_mode="HTML",
        )