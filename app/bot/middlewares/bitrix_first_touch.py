# app/bot/routers/middlewares/bitrix_first_touch.py

import logging
from aiogram import BaseMiddleware
from aiogram.types import Message

from app.integrations.bitrix.client import BitrixClient
from app.services.auto_followup_service import mark_activity
from app.services.bitrix_stage_guard import move_to_first_touch_if_needed
from app.config import ADMIN_IDS

logger = logging.getLogger(__name__)
bitrix_client = BitrixClient()


class BitrixStageGuardMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        # 🛑 middleware может получать НЕ только Message
        if not isinstance(event, Message):
            return await handler(event, data)

        # ✅ теперь event гарантированно Message
        logger.warning(
            "INCOMING MESSAGE | user_id=%s text=%r caption=%r entities=%r",
            getattr(event.from_user, "id", None),
            event.text,
            event.caption,
            event.entities,
        )

        from_user = event.from_user
        if not from_user:
            return await handler(event, data)

        # Админов не трогаем
        if from_user.id in ADMIN_IDS:
            return await handler(event, data)

        # /start не трогаем
        if event.text and event.text.startswith("/start"):
            return await handler(event, data)
        try:
            await mark_activity(from_user.id)
        except Exception:
            pass
        # 🔑 ключевая логика
        try:
            await move_to_first_touch_if_needed(
                bitrix=bitrix_client,
                tg_id=from_user.id,
            )
        except Exception as e:
            logger.exception("BitrixStageGuard error")

        return await handler(event, data)