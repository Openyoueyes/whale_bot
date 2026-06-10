# app/bot/middlewares/subscription_gate.py
from __future__ import annotations

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.services.subscription_service import (
    has_subscription_access,
    send_subscription_gate_callback,
    send_subscription_gate_message,
)


class SubscriptionGateMiddleware(BaseMiddleware):
    """
    Закрывает клиентский функционал бота до подписки на основной канал.

    Пропускает:
    - /start, чтобы стартовый обработчик мог создать пользователя/сделку и показать экран доступа;
    - callback subscription:check, чтобы пользователь мог подтвердить подписку;
    - не-private чаты, чтобы не ломать админские/служебные групповые сценарии.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        bot: Bot | None = data.get("bot")
        if bot is None:
            return await handler(event, data)

        if isinstance(event, Message):
            if self._message_is_allowed_without_subscription(event):
                return await handler(event, data)

            user_id = event.from_user.id if event.from_user else None
            if user_id is None:
                return await handler(event, data)

            if await has_subscription_access(bot, user_id):
                return await handler(event, data)

            await send_subscription_gate_message(event)
            return None

        if isinstance(event, CallbackQuery):
            if self._callback_is_allowed_without_subscription(event):
                return await handler(event, data)

            user_id = event.from_user.id if event.from_user else None
            if user_id is None:
                return await handler(event, data)

            # callback из группы/канала не блокируем
            msg = event.message
            if msg and getattr(msg.chat, "type", None) != "private":
                return await handler(event, data)

            if await has_subscription_access(bot, user_id):
                return await handler(event, data)

            await send_subscription_gate_callback(event)
            return None

        return await handler(event, data)

    @staticmethod
    def _message_is_allowed_without_subscription(message: Message) -> bool:
        if message.chat and message.chat.type != "private":
            return True

        text = (message.text or "").strip()
        if text.startswith("/start"):
            return True

        return False

    @staticmethod
    def _callback_is_allowed_without_subscription(callback: CallbackQuery) -> bool:
        return callback.data == "subscription:check"
