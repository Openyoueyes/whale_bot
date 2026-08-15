# app/bot/middlewares/throttling.py
"""
Антифлуд на клиентских хендлерах.

Каждое сообщение клиента стоит нам нескольких запросов к Bitrix и уведомлений
менеджерам. Без ограничителя один спамящий пользователь выбирает лимит вебхука
Bitrix на всех. Админов не трогаем — у них FSM-сценарии с быстрыми шагами.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import (
    ADMIN_IDS,
    CLIENT_CALLBACK_THROTTLE_SECONDS,
    CLIENT_THROTTLE_SECONDS,
)

logger = logging.getLogger(__name__)

_MAX_TRACKED_USERS = 10_000


class ThrottlingMiddleware(BaseMiddleware):
    """
    Сообщения и нажатия кнопок считаются раздельно: сообщение клиента стоит
    запросов в Bitrix и уведомлений менеджерам, а шаг квиза — только записи в БД.
    """

    def __init__(
        self,
        rate_seconds: float = CLIENT_THROTTLE_SECONDS,
        callback_rate_seconds: float = CLIENT_CALLBACK_THROTTLE_SECONDS,
    ) -> None:
        self.rate_seconds = rate_seconds
        self.callback_rate_seconds = callback_rate_seconds
        self._last_seen: dict[tuple[int, str], float] = {}
        # Предупреждаем пользователя только один раз за серию флуда.
        self._warned: set[int] = set()

    def _prune(self, now: float) -> None:
        stale = [key for key, ts in self._last_seen.items() if now - ts > 60]
        for key in stale:
            self._last_seen.pop(key, None)
            self._warned.discard(key[0])

    def _is_throttled(self, user_id: int, kind: str, rate: float) -> bool:
        now = time.monotonic()

        if len(self._last_seen) >= _MAX_TRACKED_USERS:
            self._prune(now)

        key = (user_id, kind)
        last = self._last_seen.get(key)
        self._last_seen[key] = now

        if last is not None and (now - last) < rate:
            return True

        self._warned.discard(user_id)
        return False

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, CallbackQuery):
            kind, rate = "callback", self.callback_rate_seconds
        elif isinstance(event, Message):
            kind, rate = "message", self.rate_seconds
        else:
            return await handler(event, data)

        if rate <= 0:
            return await handler(event, data)

        user = event.from_user
        if user is None or user.id in ADMIN_IDS:
            return await handler(event, data)

        if not self._is_throttled(user.id, kind, rate):
            return await handler(event, data)

        logger.debug("Throttled tg_id=%s", user.id)

        if isinstance(event, CallbackQuery):
            try:
                await event.answer("Слишком часто, подождите секунду.")
            except Exception:
                pass
        elif user.id not in self._warned:
            self._warned.add(user.id)
            try:
                await event.answer("Слишком часто 🙂 Подождите секунду и повторите.")
            except Exception:
                pass

        return None
