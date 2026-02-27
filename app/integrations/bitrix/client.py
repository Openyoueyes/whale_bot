# app/bot/integrations/bitrix/client.py
from __future__ import annotations

from typing import Any, Dict, List

import aiohttp

from app.config import (
    BITRIX_WEBHOOK_URL,
    BITRIX_PORTAL_URL,
    BITRIX_FIELD_TG_ID_LEAD,
    BITRIX_FIELD_TG_USERNAME_LEAD,
    BITRIX_FIELD_TG_LINK_LEAD,
    BITRIX_FIELD_TAG_LEAD,
    BITRIX_FIELD_TG_ID_DEAL,
    BITRIX_FIELD_TG_USERNAME_DEAL,
    BITRIX_FIELD_TG_LINK_DEAL,
    BITRIX_FIELD_TAG_DEAL,
)


class BitrixClient:
    def __init__(self, base_url: str = BITRIX_WEBHOOK_URL):
        self.base_url = base_url.rstrip("/") + "/"

    async def _post(self, method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = self.base_url + method
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, ssl=False) as resp:
                data = await resp.json()
                if resp.status != 200 or "error" in data:
                    raise RuntimeError(f"Bitrix error in {method}: {data}")
                return data

    # -------- ЛИДЫ --------
    async def set_deal_stage(self, deal_id: str | int, stage_id: str) -> None:
        """
        Смена стадии сделки (crm.deal.update).
        stage_id обычно вида: C{CATEGORY_ID}:{STATUS_ID}
        """
        payload = {
            "id": str(deal_id),
            "fields": {
                "STAGE_ID": stage_id,
            },
        }

        await self._post("crm.deal.update", payload)

    async def list_leads_by_telegram_id(self, telegram_id: int | str) -> List[Dict[str, Any]]:
        """
        Ищем лиды по кастомному полю TG_ID (lead).
        """
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
        origin_text = "Telegram Business" if origin == "business" else "Telegram Bot"

        """
        Создаём лид и заполняем UF-поля лида.
        """
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
            "COMMENTS": f"Лид из Sniper Club\nИсточник: {origin_text}",
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

    async def update_lead_username(
            self,
            lead_id: str | int,
            username: str,
    ) -> None:
        """
        Обновляем username и ссылку у существующего лида.
        """
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

    # -------- СДЕЛКИ --------

    async def list_deals_by_lead_id(self, lead_id: int | str) -> List[Dict[str, Any]]:
        """
        Ищем сделки, связанные с лидом, по стандартному полю LEAD_ID.
        """
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
        """
        Заполняем UF-поля сделки данными Telegram (id, username, link, tag).
        """
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

    @staticmethod
    def make_deal_link(deal_id: str | int) -> str:
        return f"{BITRIX_PORTAL_URL.rstrip('/')}/crm/deal/details/{deal_id}/"

    @staticmethod
    def make_lead_link(lead_id: str | int) -> str:
        return f"{BITRIX_PORTAL_URL.rstrip('/')}/crm/lead/details/{lead_id}/"

    async def list_categories(self) -> List[Dict[str, Any]]:
        """
        Список воронок (категорий сделок).

        Bitrix-особенность:
        - crm.dealcategory.list НЕ возвращает основную воронку (CATEGORY_ID = 0),
          только дополнительные.
        Поэтому добавляем основную вручную с ID=0.
        """
        data = await self._post("crm.dealcategory.list", {})
        categories: List[Dict[str, Any]] = data.get("result", [])

        # Добавляем основную воронку сделок вручную
        base_category = {
            "ID": 0,
            "NAME": "Продажи (основная)",
        }

        # Чтобы не продублировать, проверим, нет ли уже ID=0
        if not any(str(c.get("ID")) == "0" for c in categories):
            categories.insert(0, base_category)

        return categories

    async def list_stages(self, category_id: int) -> List[Dict[str, Any]]:
        """
        Список стадий воронки.
        crm.dealcategory.stage.list
        """
        payload = {"id": int(category_id)}
        data = await self._post("crm.dealcategory.stage.list", payload)
        return data.get("result", [])

    async def list_deals_for_broadcast(
            self,
            category_id: int | None = None,
            stage_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Вытащить сделки для рассылки:
        - опционально по конкретной воронке/стадии.
        ПОЛЬЗОВАТЕЛЕЙ С НЕПУСТЫМ TG_ID ОТСЕКАЕМ УЖЕ В PYTHON.
        Делает пагинацию по 'start'.
        """
        # Не фильтруем по UF-полю TG_ID на стороне Bitrix — это ненадёжно.
        filter_: Dict[str, Any] = {}
        if category_id is not None:
            filter_["CATEGORY_ID"] = int(category_id)
        if stage_id is not None:
            filter_["STAGE_ID"] = stage_id

        select = [
            "ID",
            "TITLE",
            "STAGE_ID",
            "CATEGORY_ID",
            BITRIX_FIELD_TG_ID_DEAL,
            BITRIX_FIELD_TG_USERNAME_DEAL,
            BITRIX_FIELD_TG_LINK_DEAL,
            BITRIX_FIELD_TAG_DEAL,
        ]

        deals: List[Dict[str, Any]] = []
        start: int | None = 0

        while True:
            payload = {
                "filter": filter_,
                "select": select,
            }
            if start is not None:
                payload["start"] = start

            data = await self._post("crm.deal.list", payload)
            batch = data.get("result", [])
            deals.extend(batch)

            start = data.get("next")
            if start is None:
                break

        return deals

    async def find_deal_for_telegram_user(self, telegram_id: int | str) -> Dict[str, Any] | None:
        payload = {
            "filter": {BITRIX_FIELD_TG_ID_DEAL: str(telegram_id)},
            "order": {"ID": "DESC"},
            "select": [
                "ID",
                "TITLE",
                "STAGE_ID",
                "CATEGORY_ID",
                BITRIX_FIELD_TG_ID_DEAL,
            ],
        }
        data = await self._post("crm.deal.list", payload)
        results = data.get("result", [])
        return results[0] if results else None

    async def add_deal_timeline_comment(self, deal_id: int | str, comment: str) -> None:
        """
        Пишем комментарий в таймлайн сделки.
        ENTITY_TYPE_ID=2 — сущность 'Сделка'.
        """
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
            "fields": {
                "UF_CRM_1770809839968": phone
            },
            "params": {"REGISTER_SONET_EVENT": "Y"},
        }
        await self._post("crm.deal.update", payload)

    async def get_deal(self, deal_id: int | str) -> Dict[str, Any]:
        """
        crm.deal.get — получаем поля сделки, включая ASSIGNED_BY_ID.
        """
        payload = {"id": int(deal_id)}
        data = await self._post("crm.deal.get", payload)
        return data.get("result", {}) or {}

    async def get_user(self, user_id: int | str) -> Dict[str, Any]:
        """
        user.get — получаем данные пользователя портала по ID.
        """
        payload = {"ID": int(user_id)}
        data = await self._post("user.get", payload)
        # Bitrix возвращает список
        res = data.get("result", [])
        return res[0] if res else {}