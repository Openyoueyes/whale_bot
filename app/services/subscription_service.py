# app/services/subscription_service.py
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.bot.keyboards.client import get_subscribe_inline_keyboard
from app.config import ADMIN_IDS, MAIN_CHANNEL_ID, SUBSCRIPTION_GATE_PHOTO_PATH

logger = logging.getLogger(__name__)

SUBSCRIPTION_GATE_TEXT = (
    "🐳 <b>Откройте доступ к сообществу Whale Trade Forex</b>\n\n"
    "После подписки на канал вам станут <b>БЕСПЛАТНО</b> доступны:\n\n"
    "📈 новости, торговые идеи, готовые точки входа\n"
    "🤖 тестирование торгового робота WT_FX + мониторинги с 2022 года\n"
    "📊 лучший инструмент в 2026 году для анализа рынка - авторский индикатор спроса и предложения\n"
    "🎓 2 мини-курса по трейдингу\n"
    "📩 консультация по торговле и настройке робота\n"
    "🧠 проф-тест трейдера\n\n"
    "Подпишитесь на канал и нажмите кнопку "
    "<b>«Я подписался — открыть доступ»</b>."
)

SUBSCRIPTION_NOT_FOUND_TEXT = (
    "Пока не вижу подписку на канал 👀\n\n"
    "Подпишитесь по кнопке ниже, затем вернитесь в бот и нажмите "
    "<b>«Я подписался — открыть доступ»</b>."
)

SUBSCRIPTION_REMINDER_TEXT = (
    "Упс... похоже, вы ещё не подписались на канал 👀\n\n"
    "Подпишитесь, чтобы открыть доступ к сообществу "
    "<b>Whale Trade Forex</b>."
)

_SUBSCRIPTION_REMINDER_TASKS: dict[int, asyncio.Task[None]] = {}


def _status_value(status: Any) -> str:
    """Aiogram может вернуть как строку, так и enum ChatMemberStatus."""
    if status is None:
        return ""
    return str(getattr(status, "value", status))


def _is_subscribed_member(member: Any) -> bool:
    status = _status_value(getattr(member, "status", None))

    if status in {"creator", "administrator", "member"}:
        return True

    # Для супергрупп Telegram иногда возвращает restricted + is_member=True.
    if status == "restricted" and bool(getattr(member, "is_member", False)):
        return True

    return False


def _subscription_gate_photo() -> FSInputFile | None:
    """
    Локальная картинка для стартового экрана подписки.
    Если файл не найден, бот не падает — просто отправит текст.
    """
    if not SUBSCRIPTION_GATE_PHOTO_PATH:
        return None

    path = Path(SUBSCRIPTION_GATE_PHOTO_PATH)
    if not path.is_absolute():
        path = Path.cwd() / path

    if not path.exists() or not path.is_file():
        logger.warning("Subscription gate photo not found: %s", path)
        return None

    return FSInputFile(path)


def is_subscription_check_enabled() -> bool:
    """
    Если MAIN_CHANNEL_ID не задан, не блокируем бота целиком.
    В production MAIN_CHANNEL_ID нужно обязательно прописать в .env.
    """
    return bool(MAIN_CHANNEL_ID)


async def is_user_subscribed(bot: Bot, user_id: int) -> bool:
    """
    Проверка подписки пользователя на канал.
    Важно: бот должен быть администратором канала, иначе Telegram может не дать проверить участника.
    """
    if not is_subscription_check_enabled():
        logger.warning("MAIN_CHANNEL_ID is empty. Subscription gate is disabled.")
        return True

    try:
        member = await bot.get_chat_member(chat_id=MAIN_CHANNEL_ID, user_id=user_id)
        return _is_subscribed_member(member)
    except (TelegramBadRequest, TelegramForbiddenError) as e:
        logger.warning("Cannot check subscription for user_id=%s: %s", user_id, e)
        return False
    except Exception:
        logger.exception("Unexpected subscription check error for user_id=%s", user_id)
        return False


async def has_subscription_access(bot: Bot, user_id: int) -> bool:
    """Админы всегда проходят, клиенты — только после подписки."""
    if user_id in ADMIN_IDS:
        return True
    return await is_user_subscribed(bot, user_id)


async def send_subscription_gate_message(
    message: Message,
    *,
    subscription_not_found: bool = False,
    with_photo: bool = False,
) -> None:
    text = SUBSCRIPTION_NOT_FOUND_TEXT if subscription_not_found else SUBSCRIPTION_GATE_TEXT

    if with_photo:
        photo = _subscription_gate_photo()
        if photo is not None:
            try:
                await message.answer_photo(
                    photo=photo,
                    caption=text,
                    reply_markup=get_subscribe_inline_keyboard(),
                    parse_mode="HTML",
                )
                return
            except Exception:
                logger.exception("Cannot send subscription gate photo, fallback to text")

    await message.answer(
        text,
        reply_markup=get_subscribe_inline_keyboard(),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


async def send_subscription_gate_callback(
    callback: CallbackQuery,
    *,
    subscription_not_found: bool = False,
) -> None:
    text = SUBSCRIPTION_NOT_FOUND_TEXT if subscription_not_found else SUBSCRIPTION_GATE_TEXT

    try:
        if subscription_not_found:
            await callback.answer("Пока не вижу подписку на канал", show_alert=False)
        else:
            await callback.answer()
    except Exception:
        pass

    if callback.message:
        # Если экран подписки был отправлен картинкой, обновляем подпись к картинке.
        if getattr(callback.message, "photo", None):
            try:
                await callback.message.edit_caption(
                    caption=text,
                    reply_markup=get_subscribe_inline_keyboard(),
                    parse_mode="HTML",
                )
                return
            except TelegramBadRequest:
                pass
            except Exception:
                logger.exception("Cannot edit subscription gate photo caption")

        try:
            await callback.message.edit_text(
                text,
                reply_markup=get_subscribe_inline_keyboard(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return
        except TelegramBadRequest:
            pass
        except Exception:
            logger.exception("Cannot edit subscription gate message")

        try:
            await callback.message.answer(
                text,
                reply_markup=get_subscribe_inline_keyboard(),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
        except Exception:
            logger.exception("Cannot send subscription gate message from callback")


def cancel_subscription_gate_reminder(user_id: int) -> None:
    """Отменяем отложенное напоминание, когда пользователь уже открыл доступ."""
    task = _SUBSCRIPTION_REMINDER_TASKS.pop(user_id, None)
    if task and not task.done():
        task.cancel()


def schedule_subscription_gate_reminder(
    bot: Bot,
    *,
    user_id: int,
    chat_id: int,
    delay_seconds: int = 50,
) -> None:
    """
    Через delay_seconds повторно проверяет подписку.
    Если пользователь так и не подписался — отправляет мягкое напоминание с теми же кнопками.
    """
    if user_id in ADMIN_IDS:
        return

    # Не плодим несколько одинаковых напоминаний, если пользователь нажал /start несколько раз.
    cancel_subscription_gate_reminder(user_id)

    task = asyncio.create_task(
        _subscription_gate_reminder_worker(
            bot=bot,
            user_id=user_id,
            chat_id=chat_id,
            delay_seconds=delay_seconds,
        ),
        name=f"subscription_gate_reminder_{user_id}",
    )

    def _cleanup(done_task: asyncio.Task[None]) -> None:
        if _SUBSCRIPTION_REMINDER_TASKS.get(user_id) is done_task:
            _SUBSCRIPTION_REMINDER_TASKS.pop(user_id, None)

    task.add_done_callback(_cleanup)
    _SUBSCRIPTION_REMINDER_TASKS[user_id] = task


async def _subscription_gate_reminder_worker(
    *,
    bot: Bot,
    user_id: int,
    chat_id: int,
    delay_seconds: int,
) -> None:
    try:
        await asyncio.sleep(delay_seconds)

        if await has_subscription_access(bot, user_id):
            return

        await bot.send_message(
            chat_id=chat_id,
            text=SUBSCRIPTION_REMINDER_TEXT,
            reply_markup=get_subscribe_inline_keyboard(),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Cannot send subscription reminder to user_id=%s", user_id)
