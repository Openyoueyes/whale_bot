# app/services/bitrix_presenter.py
"""
Карточка сделки для уведомлений менеджерам.

Раньше блок «ссылка на сделку + ответственный + тег» был скопирован в четырёх
сервисах и делал до четырёх запросов в Bitrix на одно действие клиента.
Теперь это одно место и один crm.deal.list (+ кэшируемый user.get).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from app.config import BITRIX_FIELD_TAG_DEAL
from app.integrations.bitrix.client import BitrixClient

logger = logging.getLogger(__name__)

bitrix_client = BitrixClient()

NO_DEAL_TEXT = "Сделка не найдена"
NO_RESPONSIBLE_TEXT = "не назначен"


@dataclass(frozen=True)
class DealCard:
    """Всё, что нужно для карточки в Telegram, в одном объекте."""

    deal_id: Optional[str] = None
    tag: Optional[str] = None
    link_text: str = NO_DEAL_TEXT
    responsible: str = NO_RESPONSIBLE_TEXT
    contact_id: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None

    @property
    def tag_text(self) -> str:
        return self.tag or "нет тега"


async def _responsible_name(assigned_id: Any) -> str:
    if not assigned_id:
        return NO_RESPONSIBLE_TEXT
    try:
        user = await bitrix_client.get_user(assigned_id)
    except Exception:
        logger.warning("Не удалось получить ответственного id=%s", assigned_id)
        return NO_RESPONSIBLE_TEXT

    first = (user.get("NAME") or "").strip()
    last = (user.get("LAST_NAME") or "").strip()
    login = (user.get("LOGIN") or "").strip()
    full = (first + " " + last).strip()
    return full or login or str(assigned_id)


async def build_deal_card(
    deal: Optional[Dict[str, Any]],
    *,
    with_responsible: bool = True,
) -> DealCard:
    """Собирает карточку из уже загруженной сделки (без лишних запросов)."""
    if not deal:
        return DealCard()

    deal_id_raw = deal.get("ID")
    if not deal_id_raw:
        return DealCard()

    deal_id = str(deal_id_raw)

    responsible = NO_RESPONSIBLE_TEXT
    if with_responsible:
        responsible = await _responsible_name(deal.get("ASSIGNED_BY_ID"))

    contact_id = deal.get("CONTACT_ID")

    # fallback: некоторые порталы отдают список контактов
    if not contact_id:
        contact_ids = deal.get("CONTACT_IDS") or []
        if isinstance(contact_ids, list) and contact_ids:
            first = contact_ids[0]
            contact_id = first.get("CONTACT_ID") if isinstance(first, dict) else first

    link = bitrix_client.make_deal_link(deal_id)

    tag_raw = deal.get(BITRIX_FIELD_TAG_DEAL)

    return DealCard(
        deal_id=deal_id,
        tag=str(tag_raw) if tag_raw else None,
        link_text=f'<a href="{link}">Перейти в сделку</a>',
        responsible=responsible,
        contact_id=str(contact_id) if contact_id else None,
        raw=deal,
    )


async def load_deal_card(tg_id: int, *, with_responsible: bool = True) -> DealCard:
    """Находит сделку клиента по TG_ID и собирает карточку. Не бросает исключений."""
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(tg_id)
    except Exception:
        logger.warning("Не удалось найти сделку для tg_id=%s", tg_id)
        deal = None

    return await build_deal_card(deal, with_responsible=with_responsible)


async def comment_safe(deal_id: Optional[str], comment: str) -> None:
    """Комментарий в таймлайн, если сделка есть. Ошибки логируем, но не пробрасываем."""
    if not deal_id:
        return
    try:
        await bitrix_client.add_deal_timeline_comment(deal_id, comment)
    except Exception:
        logger.warning("Не удалось записать комментарий в сделку %s", deal_id)
