# app/bot/middlewares/bitrix_first_touch.py

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from app.config import ADMIN_IDS
from app.integrations.bitrix.client import BitrixClient
from app.services.auto_followup_service import mark_activity
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed

logger = logging.getLogger(__name__)

bitrix_client = BitrixClient()


class BitrixStageGuardMiddleware(BaseMiddleware):
    """
    Отмечает активность клиента и возвращает застрявшую сделку в работу.

    Найденную сделку кладём в data["bitrix_deal"] — хендлер переиспользует её
    вместо повторного запроса в Bitrix.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message):
            return await handler(event, data)

        from_user = event.from_user
        if not from_user:
            return await handler(event, data)

        # Админов и /start не трогаем: у /start свой сценарий синхронизации.
        if from_user.id in ADMIN_IDS:
            return await handler(event, data)
        if event.text and event.text.startswith("/start"):
            return await handler(event, data)

        try:
            await mark_activity(from_user.id)
        except Exception:
            logger.warning("Не удалось отметить активность tg_id=%s", from_user.id)

        try:
            data["bitrix_deal"] = await move_to_first_touch_if_needed(
                bitrix=bitrix_client,
                tg_id=from_user.id,
            )
        except Exception:
            logger.exception("BitrixStageGuard error tg_id=%s", from_user.id)
            data["bitrix_deal"] = None

        return await handler(event, data)
