# app/services/bitrix_stage_guard.py

from app.integrations.bitrix.client import BitrixClient

BAD_STATUS_IDS = {
    "NEW",
    "UC_F3ZLGB",
    "UC_LX2TD7",

    "LOSE",
    "UC_R1NGXP",
    "UC_OMS9IC",

    "UC_6OBDV3",
}

FIRST_TOUCH_STATUS_ID = "PREPARATION"  # если у тебя 1 касание = другой статус, поменяй тут


def _extract_status_id(stage_id: str) -> str:
    # "C1:LOSE" -> "LOSE", "LOSE" -> "LOSE"
    return stage_id.split(":")[-1].strip() if stage_id else ""


def _build_stage_id(category_id: int | None, status_id: str) -> str:
    try:
        cid = int(category_id or 0)
    except (TypeError, ValueError):
        cid = 0
    return f"C{cid}:{status_id}" if cid > 0 else status_id


async def move_to_first_touch_if_needed(bitrix: BitrixClient, tg_id: int) -> bool:
    deal = await bitrix.find_deal_for_telegram_user(tg_id)
    if not deal:
        return False

    stage_id = str(deal.get("STAGE_ID") or "")
    status_id = _extract_status_id(stage_id)

    if status_id not in BAD_STATUS_IDS:
        return False

    target_stage = _build_stage_id(deal.get("CATEGORY_ID"), FIRST_TOUCH_STATUS_ID)

    if stage_id == target_stage:
        return False

    await bitrix.set_deal_stage(deal_id=deal["ID"], stage_id=target_stage)
    return True