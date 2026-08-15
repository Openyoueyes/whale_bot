# app/services/bitrix_stage_guard.py
"""
Любая активность клиента возвращает сделку в работу («1 касание»),
если она застряла в «мёртвых» стадиях.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.integrations.bitrix.client import BitrixClient
from app.services.bitrix_stages import (
    BAD_STATUS_IDS,
    STATUS_FIRST_TOUCH,
    stage_id_for_deal,
    status_from_stage_id,
)

logger = logging.getLogger(__name__)


async def move_to_first_touch_if_needed(
    bitrix: BitrixClient,
    tg_id: int,
    *,
    deal: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Переводит сделку клиента в стадию «1 касание», если она в «плохой» стадии.

    Возвращает сделку (в том виде, в каком её отдал Bitrix) — вызывающий код
    может переиспользовать её вместо повторного запроса.
    """
    if deal is None:
        deal = await bitrix.find_deal_for_telegram_user(tg_id)

    if not deal:
        return None

    stage_id = str(deal.get("STAGE_ID") or "")
    if status_from_stage_id(stage_id) not in BAD_STATUS_IDS:
        return deal

    target_stage = stage_id_for_deal(deal, STATUS_FIRST_TOUCH)
    if stage_id == target_stage:
        return deal

    await bitrix.set_deal_stage(deal_id=deal["ID"], stage_id=target_stage)
    logger.info("Сделка %s переведена в %s (активность клиента)", deal.get("ID"), target_stage)
    return deal
