# app/integrations/bitrix/client.py
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, ClassVar, Dict, List, Optional

import aiohttp

from app.config import (
    BITRIX_WEBHOOK_URL,
    BITRIX_PORTAL_URL,
    BITRIX_MAX_RPS,
    BITRIX_TIMEOUT_SECONDS,
    BITRIX_VERIFY_SSL,
    BITRIX_FIELD_TG_ID_LEAD,
    BITRIX_FIELD_TG_USERNAME_LEAD,
    BITRIX_FIELD_TG_LINK_LEAD,
    BITRIX_FIELD_TAG_LEAD,
    BITRIX_FIELD_TG_ID_DEAL,
    BITRIX_FIELD_TG_USERNAME_DEAL,
    BITRIX_FIELD_TG_LINK_DEAL,
    BITRIX_FIELD_TAG_DEAL,
    BITRIX_FIELD_PHONE_DEAL,
)

logger = logging.getLogger(__name__)

# Ошибки Bitrix, на которых имеет смысл повторить запрос.
_RETRYABLE_ERRORS = {"QUERY_LIMIT_EXCEEDED", "OPERATION_TIME_LIMIT"}

# Поля сделки, которых хватает и для карточки менеджера, и для рассылки:
# ASSIGNED_BY_ID и CONTACT_ID избавляют от дополнительного crm.deal.get.
DEAL_SELECT_FIELDS: List[str] = [
    "ID",
    "TITLE",
    "STAGE_ID",
    "CATEGORY_ID",
    "ASSIGNED_BY_ID",
    "CONTACT_ID",
    BITRIX_FIELD_TG_ID_DEAL,
    BITRIX_FIELD_TG_USERNAME_DEAL,
    BITRIX_FIELD_TG_LINK_DEAL,
    BITRIX_FIELD_TAG_DEAL,
]


class BitrixError(RuntimeError):
    """Ошибка вызова Bitrix REST."""


class _RateLimiter:
    """
    Простой ограничитель: не чаще N запросов в секунду на весь процесс.
    Вебхук Bitrix общий, поэтому лимитер общий для всех экземпляров клиента.
    """

    def __init__(self, rps: float) -> None:
        self._interval = 1.0 / rps if rps > 0 else 0.0
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def acquire(self) -> None:
        if self._interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_at = now + self._interval


class BitrixClient:
    """
    Клиент Bitrix REST поверх входящего вебхука.

    Экземпляры дешёвые и без состояния: HTTP-сессия, лимитер и кэш
    пользователей портала общие на уровне класса.
    """

    _session: ClassVar[Optional[aiohttp.ClientSession]] = None
    _session_lock: ClassVar[asyncio.Lock] = asyncio.Lock()
    _limiter: ClassVar[_RateLimiter] = _RateLimiter(BITRIX_MAX_RPS)
    _user_cache: ClassVar[Dict[str, Dict[str, Any]]] = {}

    def __init__(self, base_url: str = BITRIX_WEBHOOK_URL):
        self.base_url = base_url.rstrip("/") + "/"

    # ------------------------------------------------------------------
    # инфраструктура
    # ------------------------------------------------------------------

    @classmethod
    async def _get_session(cls) -> aiohttp.ClientSession:
        if cls._session is not None and not cls._session.closed:
            return cls._session

        async with cls._session_lock:
            if cls._session is None or cls._session.closed:
                cls._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=BITRIX_TIMEOUT_SECONDS),
                    connector=aiohttp.TCPConnector(
                        limit=20,
                        ssl=None if BITRIX_VERIFY_SSL else False,
                    ),
                )
        return cls._session

    @classmethod
    async def close(cls) -> None:
        """Закрыть общую HTTP-сессию (вызывается при остановке бота)."""
        session = cls._session
        cls._session = None
        if session is not None and not session.closed:
            await session.close()

    async def _post(
        self,
        method: str,
        payload: Dict[str, Any],
        *,
        retries: int = 2,
    ) -> Dict[str, Any]:
        url = self.base_url + method

        for attempt in range(retries + 1):
            await self._limiter.acquire()
            session = await self._get_session()

            try:
                async with session.post(url, json=payload) as resp:
                    status = resp.status
                    data = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise BitrixError(f"Bitrix network error in {method}: {e!r}") from e

            if not isinstance(data, dict):
                raise BitrixError(f"Bitrix returned non-object in {method}: {data!r}")

            error = data.get("error")
            if status == 200 and not error:
                return data

            if error in _RETRYABLE_ERRORS and attempt < retries:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue

            raise BitrixError(f"Bitrix error in {method}: {data}")

        raise BitrixError(f"Bitrix error in {method}: retries exhausted")

    # ------------------------------------------------------------------
    # ЛИДЫ
    # ------------------------------------------------------------------

    async def list_leads_by_telegram_id(self, telegram_id: int | str) -> List[Dict[str, Any]]:
        """Ищем лиды по кастомному полю TG_ID (lead)."""
        payload = {
            "filter": {BITRIX_FIELD_TG_ID_LEAD: str(telegram_id)},
            "select": [
                "ID",
                "TITLE",
                BITRIX_FIELD_TG_ID_LEAD,
                BITRIX_FIELD_TG_USERNAME_LEAD,
                BITRIX_FIELD_TG_LINK_LEAD,
                BITRIX_FIELD_TAG_LEAD,
            ],
        }
        data = await self._post("crm.lead.list", payload)
        return data.get("result", [])

    async def create_lead(
        self,
        user_info: Dict[str, Any],
        tag: str | None,
        *,
        origin: str = "bot",
    ) -> Dict[str, Any]:
        """Создаём лид и заполняем UF-поля лида."""
        origin_text = "Telegram Business" if origin == "business" else "Telegram Bot"

        user_link_tg = (
            f"https://t.me/{user_info['username']}"
            if user_info.get("username")
            else ""
        )
        name = user_info.get("first_name") or ""
        last = user_info.get("last_name") or ""
        full_name = (name + " " + last).strip() or "Без имени"

        fields: Dict[str, Any] = {
            "NAME": full_name,
            "COMMENTS": f"Лид из Whale Trade\nИсточник: {origin_text}",
            "SOURCE_ID": "WEB",
            BITRIX_FIELD_TG_ID_LEAD: str(user_info["id"]),
            BITRIX_FIELD_TG_USERNAME_LEAD: user_info.get("username"),
            BITRIX_FIELD_TG_LINK_LEAD: user_link_tg,
        }

        if tag:
            fields[BITRIX_FIELD_TAG_LEAD] = tag

        payload = {
            "fields": fields,
            "params": {"REGISTER_SONET_EVENT": "Y"},
        }

        data = await self._post("crm.lead.add", payload)
        return data  # data["result"] = ID лида

    async def update_lead_username(self, lead_id: str | int, username: str) -> None:
        """Обновляем username и ссылку у существующего лида."""
        user_link_tg = f"https://t.me/{username}" if username else ""
        payload = {
            "id": lead_id,
            "fields": {
                BITRIX_FIELD_TG_USERNAME_LEAD: username,
                BITRIX_FIELD_TG_LINK_LEAD: user_link_tg,
            },
            "params": {"REGISTER_SONET_EVENT": "Y"},
        }
        await self._post("crm.lead.update", payload)

    # ------------------------------------------------------------------
    # СДЕЛКИ
    # ------------------------------------------------------------------

    async def set_deal_stage(self, deal_id: str | int, stage_id: str) -> None:
        """
        Смена стадии сделки (crm.deal.update).
        stage_id обычно вида: C{CATEGORY_ID}:{STATUS_ID}
        """
        payload = {
            "id": str(deal_id),
            "fields": {"STAGE_ID": stage_id},
        }
        await self._post("crm.deal.update", payload)

    async def list_deals_by_lead_id(self, lead_id: int | str) -> List[Dict[str, Any]]:
        """Ищем сделки, связанные с лидом, по стандартному полю LEAD_ID."""
        payload = {
            "filter": {"LEAD_ID": int(lead_id)},
            "select": ["ID", "TITLE", "LEAD_ID"],
        }
        data = await self._post("crm.deal.list", payload)
        return data.get("result", [])

    async def update_deal_fields_from_user(
        self,
        deal_id: int | str,
        user_info: Dict[str, Any],
        tag: str | None,
    ) -> None:
        """Заполняем UF-поля сделки данными Telegram (id, username, link, tag)."""
        user_link_tg = (
            f"https://t.me/{user_info['username']}"
            if user_info.get("username")
            else ""
        )

        fields: Dict[str, Any] = {
            BITRIX_FIELD_TG_ID_DEAL: str(user_info["id"]),
            BITRIX_FIELD_TG_USERNAME_DEAL: user_info.get("username"),
            BITRIX_FIELD_TG_LINK_DEAL: user_link_tg,
        }
        if tag:
            fields[BITRIX_FIELD_TAG_DEAL] = tag

        payload = {
            "id": int(deal_id),
            "fields": fields,
            "params": {"REGISTER_SONET_EVENT": "Y"},
        }
        await self._post("crm.deal.update", payload)

    async def list_deals_for_broadcast(
        self,
        category_id: int | None = None,
        stage_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Сделки для рассылки/воркеров: опционально по воронке и стадии.
        Пустой TG_ID отсекаем уже в Python — фильтр по UF-полю на стороне
        Bitrix работает ненадёжно. Пагинация по 'start'.
        """
        filter_: Dict[str, Any] = {}
        if category_id is not None:
            filter_["CATEGORY_ID"] = int(category_id)
        if stage_id is not None:
            filter_["STAGE_ID"] = stage_id

        deals: List[Dict[str, Any]] = []
        start: int | None = 0

        while True:
            payload: Dict[str, Any] = {
                "filter": filter_,
                "select": DEAL_SELECT_FIELDS,
            }
            if start is not None:
                payload["start"] = start

            data = await self._post("crm.deal.list", payload)
            deals.extend(data.get("result", []))

            start = data.get("next")
            if start is None:
                break

        return deals

    async def find_deal_for_telegram_user(self, telegram_id: int | str) -> Dict[str, Any] | None:
        """
        Последняя сделка клиента по TG_ID.
        Возвращает сразу ASSIGNED_BY_ID и CONTACT_ID, поэтому отдельный
        crm.deal.get для карточки менеджера не нужен.
        """
        payload = {
            "filter": {BITRIX_FIELD_TG_ID_DEAL: str(telegram_id)},
            "order": {"ID": "DESC"},
            "select": DEAL_SELECT_FIELDS,
        }
        data = await self._post("crm.deal.list", payload)
        results = data.get("result", [])
        return results[0] if results else None

    async def add_deal_timeline_comment(self, deal_id: int | str, comment: str) -> None:
        """Комментарий в таймлайн сделки. ENTITY_TYPE_ID=2 — сущность 'Сделка'."""
        payload = {
            "fields": {
                "ENTITY_TYPE_ID": 2,
                "ENTITY_ID": int(deal_id),
                "COMMENT": comment,
            }
        }
        await self._post("crm.timeline.comment.add", payload)

    async def update_deal_phone(self, deal_id: str | int, phone: str) -> None:
        payload = {
            "id": int(deal_id),
            "fields": {BITRIX_FIELD_PHONE_DEAL: phone},
            "params": {"REGISTER_SONET_EVENT": "Y"},
        }
        await self._post("crm.deal.update", payload)

    async def get_deal(self, deal_id: int | str) -> Dict[str, Any]:
        """crm.deal.get — полный набор полей сделки."""
        payload = {"id": int(deal_id)}
        data = await self._post("crm.deal.get", payload)
        return data.get("result", {}) or {}

    # ------------------------------------------------------------------
    # ВОРОНКИ И СТАДИИ
    # ------------------------------------------------------------------

    async def list_categories(self) -> List[Dict[str, Any]]:
        """
        Список воронок (категорий сделок).

        Bitrix-особенность: crm.dealcategory.list НЕ возвращает основную
        воронку (CATEGORY_ID = 0), поэтому добавляем её вручную.
        """
        data = await self._post("crm.dealcategory.list", {})
        categories: List[Dict[str, Any]] = data.get("result", [])

        if not any(str(c.get("ID")) == "0" for c in categories):
            categories.insert(0, {"ID": 0, "NAME": "Продажи (основная)"})

        return categories

    async def list_stages(self, category_id: int) -> List[Dict[str, Any]]:
        """Список стадий воронки (crm.dealcategory.stage.list)."""
        payload = {"id": int(category_id)}
        data = await self._post("crm.dealcategory.stage.list", payload)
        return data.get("result", [])

    # ------------------------------------------------------------------
    # ПОЛЬЗОВАТЕЛИ ПОРТАЛА И КОНТАКТЫ
    # ------------------------------------------------------------------

    async def get_user(self, user_id: int | str) -> Dict[str, Any]:
        """
        user.get — данные сотрудника портала по ID.
        Кэшируем: сотрудников десятки, а спрашиваем мы их на каждое действие клиента.
        """
        key = str(user_id)
        cached = self._user_cache.get(key)
        if cached is not None:
            return cached

        payload = {"ID": int(user_id)}
        data = await self._post("user.get", payload)
        res = data.get("result", [])
        user = res[0] if res else {}

        if user:
            self._user_cache[key] = user
        return user

    async def get_contact(self, contact_id: int | str) -> Dict[str, Any]:
        """crm.contact.get — вернёт result { ... "NAME": "Алексей Дмитриев", ... }"""
        payload = {"id": int(contact_id)}
        data = await self._post("crm.contact.get", payload)
        return data.get("result", {}) or {}

    # ------------------------------------------------------------------
    # ССЫЛКИ
    # ------------------------------------------------------------------

    @staticmethod
    def make_deal_link(deal_id: str | int) -> str:
        return f"{BITRIX_PORTAL_URL.rstrip('/')}/crm/deal/details/{deal_id}/"

    @staticmethod
    def make_lead_link(lead_id: str | int) -> str:
        return f"{BITRIX_PORTAL_URL.rstrip('/')}/crm/lead/details/{lead_id}/"
