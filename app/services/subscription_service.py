# app/services/subscription_service.py
from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message

from app.bot.keyboards.client import get_subscribe_inline_keyboard
from app.config import ADMIN_IDS, MAIN_CHANNEL_ID

logger = logging.getLogger(__name__)

SUBSCRIPTION_GATE_TEXT = (
    "🐳 <b>Откройте бесплатный доступ к Whale Trade</b>\n\n"
    "После подписки на канал вам станут доступны:\n\n"
    "🤖 тестирование торгового робота WhaleTrade AI\n"
    "📊 авторский индикатор для анализа рынка\n"
    "🎓 мини-курс по трейдингу\n"
    "📩 консультация по торговле и настройке робота\n"
    "📈 новости, разборы и торговые идеи\n\n"
    "Подпишитесь на канал и нажмите кнопку "
    "<b>«Я подписался — открыть доступ»</b>."
)

SUBSCRIPTION_NOT_FOUND_TEXT = (
    "Пока не вижу подписку на канал 👀\n\n"
    "Подпишитесь по кнопке ниже, затем вернитесь в бот и нажмите "
    "<b>«Я подписался — открыть доступ»</b>."
)


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
) -> None:
    text = SUBSCRIPTION_NOT_FOUND_TEXT if subscription_not_found else SUBSCRIPTION_GATE_TEXT
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
        await callback.answer(
            "Сначала подпишитесь на канал" if subscription_not_found else None,
            show_alert=False,
        )
    except Exception:
        pass

    if callback.message:
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
