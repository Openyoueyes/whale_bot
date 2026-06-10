# app/bot/routers/client/base.py
from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import CallbackQuery, Message, User

from app.bot.keyboards.client import get_main_menu_keyboard
from app.bot.keyboards.quiz import get_quiz_start_inline_kb
from app.config import WELCOME_PHOTO_FILE_ID
from app.db.session import async_session_maker
from app.services.auto_followup_service import mark_activity, mark_start
from app.services.bitrix_service import sync_user_with_bitrix_on_start
from app.services.dialog_service import process_client_message
from app.services.subscription_service import (
    has_subscription_access,
    send_subscription_gate_callback,
    send_subscription_gate_message,
)
from app.services.triggers_service import (
    get_trigger_by_keyword,
    normalize_keyword,
    send_trigger_reply,
)
from app.services.user_service import (
    get_or_create_tg_user,
    process_referral_tag_for_user,
)

logger = logging.getLogger(__name__)

MAIN_MENU_TEXTS = {
    "💰 Whale Профит",
    "🤖 Торговые роботы",
    "🎁 Бонус",
    "📞 Связь с менеджером",
}

router = Router(name="client-base")


def _safe_first_name_from_user(user: User | None) -> str:
    """
    Имя для приветствия.
    Берём first_name из Telegram, если пусто — 'трейдер'.
    """
    name = (user.first_name or "").strip() if user else ""
    return name or "трейдер"


def _build_welcome_caption(first_name: str) -> str:
    return (
        f"👋 <b>{first_name}</b>, вас приветствует команда WhaleTrade 🐳\n\n"
        "Спасибо за интерес к нашей работе!\n\n"
        "Мы торгуем на рынке <b>Forex</b>.\n"
        "Ищем партнеров для совместных идей и их реализаций.\n\n"
        "<b>Два направления сотрудничества:</b>\n\n"
        "1️⃣ Готовые точки входа с аналитикой и сопровождением — WhaleTrade Профит.\n\n"
        "2️⃣ Торговые роботы WhaleTrade — статистика с 2022 года.\n\n"
        "<b>Отзывы работы с нами: @WhaleInvestmentTrading</b>\n\n"
        "📌 Пройдите <b>короткий проф-тест из 5 вопросов</b> и определите направление, "
        "которое подходит именно вам 👇"
    )


async def _send_welcome_flow(message: Message) -> None:
    first_name = _safe_first_name_from_user(message.from_user)
    caption = _build_welcome_caption(first_name)

    if WELCOME_PHOTO_FILE_ID:
        await message.answer_photo(
            photo=WELCOME_PHOTO_FILE_ID,
            caption=caption,
            reply_markup=get_quiz_start_inline_kb(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            caption,
            reply_markup=get_quiz_start_inline_kb(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    await message.answer(
        "\u2060",
        reply_markup=get_main_menu_keyboard(),
    )


async def _send_welcome_flow_to_callback_chat(callback: CallbackQuery) -> None:
    if not callback.message:
        return

    first_name = _safe_first_name_from_user(callback.from_user)
    caption = _build_welcome_caption(first_name)
    chat_id = callback.message.chat.id

    if WELCOME_PHOTO_FILE_ID:
        await callback.bot.send_photo(
            chat_id=chat_id,
            photo=WELCOME_PHOTO_FILE_ID,
            caption=caption,
            reply_markup=get_quiz_start_inline_kb(),
            parse_mode="HTML",
        )
    else:
        await callback.bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=get_quiz_start_inline_kb(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    await callback.bot.send_message(
        chat_id=chat_id,
        text="\u2060",
        reply_markup=get_main_menu_keyboard(),
    )


@router.message(CommandStart())
async def cmd_start(message: Message, command: CommandObject):
    from_user = message.from_user
    if not from_user:
        return

    start_tag = (command.args or "").strip()

    user_info = {
        "first_name": from_user.first_name,
        "last_name": from_user.last_name,
        "username": from_user.username,
        "id": from_user.id,
    }

    # 1) TG user + referral tag
    async with async_session_maker() as session:
        try:
            tg_user = await get_or_create_tg_user(session, from_user)
            tag_value, is_first_visit = await process_referral_tag_for_user(session, tg_user, start_tag)
            await session.commit()
            logger.warning("TG_USER_OK tg_id=%s db_id=%s", from_user.id, tg_user.id)
        except Exception:
            logger.exception("TG_USER_FAIL tg_id=%s", from_user.id)
            await session.rollback()
            raise

    # 2) Bitrix sync (ВАЖНО: забираем deal_id)
    lead_id, deal_id = await sync_user_with_bitrix_on_start(
        bot=message.bot,
        user_info=user_info,
        tag_value=tag_value,
        is_first_visit=is_first_visit,
        origin="bot",
    )

    # 3) фиксируем старт для авто-воркеров
    try:
        await mark_start(from_user.id, deal_id)
    except Exception:
        pass

    # 4) Доступ к боту только после подписки
    if not await has_subscription_access(message.bot, from_user.id):
        await send_subscription_gate_message(message)
        return

    await _send_welcome_flow(message)


@router.callback_query(F.data == "subscription:check")
async def subscription_check(callback: CallbackQuery):
    if not callback.from_user:
        return

    if not await has_subscription_access(callback.bot, callback.from_user.id):
        await send_subscription_gate_callback(callback, subscription_not_found=True)
        return

    try:
        await callback.answer("✅ Подписка подтверждена")
    except Exception:
        pass

    if callback.message:
        try:
            await callback.message.delete()
        except TelegramBadRequest:
            pass
        except Exception:
            pass

    await _send_welcome_flow_to_callback_chat(callback)


def _trigger_key_from_message(message: Message) -> str:
    """
    Триггер ищем только по тексту/подписи.
    Если клиент отправил чистое медиа без текста — триггер не срабатывает.
    """
    raw = (message.text or message.caption or "").strip()
    return normalize_keyword(raw)


@router.message(
    # НЕ команды
    ~F.text.startswith("/"),
    # НЕ пункты главного меню
    ~F.text.in_(MAIN_MENU_TEXTS),
    # НЕ перехватывать контакты/тест-флоу
    ~F.contact,
)
async def any_client_message(message: Message):
    try:
        await mark_activity(message.from_user.id)
    except Exception:
        pass

    # триггеры
    try:
        key = _trigger_key_from_message(message)
        if key:
            async with async_session_maker() as session:
                trigger = await get_trigger_by_keyword(session, key)

            if trigger and trigger.is_enabled:
                await send_trigger_reply(message.bot, message.chat.id, trigger)
                # если НЕ надо дальше в Bitrix — раскомментируйте:
                # return
    except Exception:
        pass

    await process_client_message(message.bot, message)
