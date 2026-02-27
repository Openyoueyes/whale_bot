# app/services/business_service.py

from __future__ import annotations

import asyncio
from typing import Dict, Any

from aiogram import Bot
from aiogram.types import Message

from app.db.session import async_session_maker
from app.services.user_service import get_or_create_tg_user
from app.services.bitrix_service import sync_user_with_bitrix_on_start
from app.integrations.bitrix.client import BitrixClient

bitrix = BitrixClient()

# ВАЖНО: локи на одного клиента (tg_id)
_CLIENT_LOCKS: Dict[int, asyncio.Lock] = {}


def _get_lock(client_id: int) -> asyncio.Lock:
    lock = _CLIENT_LOCKS.get(client_id)
    if lock is None:
        lock = asyncio.Lock()
        _CLIENT_LOCKS[client_id] = lock
    return lock


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


async def ensure_deal_id_for_private_chat(bot: Bot, message: Message) -> str | None:
    if not _is_private_chat(message):
        return None

    client_id = _client_tg_id(message)

    # ---- КРИТИЧЕСКИ ВАЖНО: сериализуем обработку на одного клиента ----
    async with _get_lock(client_id):

        # 1) БД
        async with async_session_maker() as session:
            await get_or_create_tg_user(session, message.chat)
            await session.commit()

        # 2) Сразу пробуем найти сделку по TG_ID
        try:
            deal = await bitrix.find_deal_for_telegram_user(client_id)
            if deal:
                return str(deal["ID"])
        except Exception:
            pass

        # 3) Создаём лид (silent) — но только один раз, из-за лока
        user_info = _build_user_info_from_chat(message)
        lead_id, deal_id = await sync_user_with_bitrix_on_start(
            bot=bot,
            user_info=user_info,
            tag_value=None,
            is_first_visit=True,
            silent=True,
            origin="business",
        )

        # 4) Если deal_id уже вернулся — отлично
        if deal_id:
            return deal_id

        # 5) Иначе ждём сделку от робота
        if lead_id is not None:
            for _ in range(7):  # чуть больше попыток
                await asyncio.sleep(2)
                try:
                    deals = await bitrix.list_deals_by_lead_id(lead_id)
                    if deals:
                        return str(deals[0]["ID"])
                except Exception:
                    pass

        # 6) Последняя попытка: вдруг робот уже проставил TG_ID в сделку
        try:
            deal = await bitrix.find_deal_for_telegram_user(client_id)
            if deal:
                return str(deal["ID"])
        except Exception:
            pass

        return None
