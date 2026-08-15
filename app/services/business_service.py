# app/services/business_service.py

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import Message

from app.db.session import async_session_maker
from app.integrations.bitrix.client import BitrixClient
from app.services.bitrix_service import sync_user_with_bitrix_locked
from app.services.locks import client_lock
from app.services.user_service import get_or_create_tg_user

logger = logging.getLogger(__name__)

bitrix = BitrixClient()

# Сколько ждём сделку, которую создаёт робот Bitrix по новому лиду.
_DEAL_WAIT_ATTEMPTS = 7
_DEAL_WAIT_DELAY = 2.0


def _is_private_chat(message: Message) -> bool:
    return bool(message.chat and message.chat.type == "private")


def _client_tg_id(message: Message) -> int:
    return int(message.chat.id)


def _build_user_info_from_chat(message: Message) -> Dict[str, Any]:
    return {
        "first_name": getattr(message.chat, "first_name", None),
        "last_name": getattr(message.chat, "last_name", None),
        "username": getattr(message.chat, "username", None),
        "id": _client_tg_id(message),
    }


async def ensure_deal_id_for_private_chat(bot: Bot, message: Message) -> Optional[str]:
    """
    Гарантирует, что у клиента из Business-диалога есть сделка в Bitrix.
    Обработка одного клиента сериализована локом (общим с /start-сценарием),
    поэтому параллельные сообщения не создадут дубли лидов.
    """
    if not _is_private_chat(message):
        return None

    client_id = _client_tg_id(message)

    async with client_lock(client_id):
        async with async_session_maker() as session:
            await get_or_create_tg_user(session, message.chat)
            await session.commit()

        try:
            deal = await bitrix.find_deal_for_telegram_user(client_id)
            if deal:
                return str(deal["ID"])
        except Exception:
            logger.warning("Не удалось найти сделку для business-клиента %s", client_id)

        # Лок уже взят выше — используем вариант без повторного захвата.
        lead_id, deal_id = await sync_user_with_bitrix_locked(
            bot=bot,
            user_info=_build_user_info_from_chat(message),
            tag_value=None,
            is_first_visit=True,
            silent=True,
            origin="business",
        )

        if deal_id:
            return deal_id

        # Сделку создаёт робот Bitrix — ждём её появления.
        if lead_id is not None:
            for _ in range(_DEAL_WAIT_ATTEMPTS):
                await asyncio.sleep(_DEAL_WAIT_DELAY)
                try:
                    deals = await bitrix.list_deals_by_lead_id(lead_id)
                    if deals:
                        return str(deals[0]["ID"])
                except Exception:
                    logger.warning("Не удалось получить сделки лида %s", lead_id)

        # Последняя попытка: вдруг робот уже проставил TG_ID в сделку.
        try:
            deal = await bitrix.find_deal_for_telegram_user(client_id)
            if deal:
                return str(deal["ID"])
        except Exception:
            logger.warning("Финальный поиск сделки не удался для %s", client_id)

        return None
