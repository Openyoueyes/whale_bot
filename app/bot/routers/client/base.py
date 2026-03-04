# app/bot/routers/client/base.py
from __future__ import annotations

import asyncio
from typing import Set

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.filters.command import CommandObject
from aiogram.types import Message

from app.bot.keyboards.quiz import get_quiz_start_inline_kb
from app.config import (
    ADMIN_IDS, MAIN_CHANNEL_ID, WELCOME_PHOTO_FILE_ID
)
from app.db.session import async_session_maker
from app.services.auto_followup_service import mark_activity, mark_start
from app.services.dialog_service import process_client_message
from app.services.triggers_service import (
    get_trigger_by_keyword,
    send_trigger_reply,
    normalize_keyword,
)
from app.services.user_service import (
    get_or_create_tg_user,
    process_referral_tag_for_user,
)
from app.services.bitrix_service import sync_user_with_bitrix_on_start
from app.bot.keyboards.client import get_main_menu_keyboard, get_subscribe_inline_keyboard
import logging

logger = logging.getLogger(__name__)

MAIN_MENU_TEXTS = {
    "💰 Whale Профит",
    "🤖 Торговые роботы",
    "🎁 Бонус",
    "📞 Связь с менеджером",
}

router = Router(name="client-base")

# Анти-дубль: не планируем много напоминаний одному и тому же юзеру
_scheduled_subscribe_reminders: Set[int] = set()


def _safe_first_name(message: Message) -> str:
    """
    Имя для приветствия.
    Берём first_name из Telegram, если пусто — 'друг'.
    """
    u = message.from_user
    name = (u.first_name or "").strip() if u else ""
    return name or "трейдер"


def _is_subscribed_status(status: str | None) -> bool:
    # Для канала: member/administrator/creator = подписан
    return status in ("member", "administrator", "creator")


async def _is_user_subscribed(bot: Bot, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=MAIN_CHANNEL_ID, user_id=user_id)
        return _is_subscribed_status(getattr(member, "status", None))
    except Exception:
        # Если не смогли проверить — считаем "не подписан", чтобы напоминание сработало
        return False


async def _send_subscribe_reminder(bot: Bot, chat_id: int, user_id: int, first_name: str) -> None:
    """
    first_name передаём внутрь, чтобы не дёргать Telegram API.
    """
    try:
        await asyncio.sleep(240)  # 5 минут

        # Повторная проверка перед отправкой
        if await _is_user_subscribed(bot, user_id):
            return

        # если не хочешь имя в напоминании — убери первую строку
        caption = (
            f"{first_name}, кажется, вы ещё не подписались на наш основной канал.\n\n"
            "Подпишитесь — там много обучающей и полезной информации, разборы сделок и материалы.\n\n"
            "👇 Нажми кнопку ниже, чтобы подписаться:"
        )

        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=get_subscribe_inline_keyboard(),
            disable_web_page_preview=True,
        )

    except Exception:
        pass
    finally:
        _scheduled_subscribe_reminders.discard(user_id)


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

    # ✅ персонализация
    first_name = _safe_first_name(message)

    caption = (
        f"👋 <b>{first_name}</b>, вас приветствует команда WhaleTrade 🐳\n\n"
        f"Спасибо за интерес к нашей работе!\n\n"
        "Мы торгуем на рынке <b>Forex</b>.\n"
        "Ищем партнеров для совместных идей и их реализаций.\n\n"
        "<b>Два напраления сотрудничества:</b>\n\n"
        "1️⃣Готовые точки входа с аналитикой и сопровождением(WhaleTade Профит).\n\n"
        "2️⃣Торговые роботы WhaleTrade(статистика с 2022 года).\n\n"

        "<b>Отзывы работы с нами: @WhaleInvestmentTrading</b>\n\n"
       
        "📣 Так же <b>подпишитесь</b> на наш открытый канал там много разборов и полезной информации:\nhttps://t.me/+on4x8BSxxv5hZmYy\n\n"

        "📌Пройдите <b>короткий проф-тест из 5-ти вопросов</b> и определите направление которое подходит именно вам👇"
    )

    # 1) Видео + текст (caption) + инлайн-кнопка
    if WELCOME_PHOTO_FILE_ID:
        await message.answer_photo(
            photo=WELCOME_PHOTO_FILE_ID,
            caption=caption,
            reply_markup=get_quiz_start_inline_kb(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    else:
        await message.answer(
            caption,
            reply_markup=get_quiz_start_inline_kb(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )

    # 2) Отдельным сообщением показываем реплай-меню
    await message.answer(
        "\u2060",
        reply_markup=get_main_menu_keyboard(),
    )

    # 3) Планируем напоминание через 5 минут (если НЕ админ)
    if from_user.id not in ADMIN_IDS:
        should_schedule = True
        try:
            if await _is_user_subscribed(message.bot, from_user.id):
                should_schedule = False
        except Exception:
            should_schedule = True

        if should_schedule and from_user.id not in _scheduled_subscribe_reminders:
            _scheduled_subscribe_reminders.add(from_user.id)

            _task = asyncio.create_task(
                _send_subscribe_reminder(
                    bot=message.bot,
                    chat_id=message.chat.id,
                    user_id=from_user.id,
                    first_name=first_name,
                )
            )


def _is_menu_or_command(message: Message) -> bool:
    t = (message.text or "").strip()
    if not t:
        return False
    if t in MAIN_MENU_TEXTS:
        return True
    if t.startswith("/"):
        return True
    return False


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
    if message.from_user and message.from_user.id in ADMIN_IDS:
        return
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
