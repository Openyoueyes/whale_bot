# app/services/bitrix_stages.py
"""
Единственный источник правды по стадиям сделок Bitrix.

Bitrix отдаёт STAGE_ID в двух форматах:
  - "NEW"        — основная воронка (CATEGORY_ID = 0)
  - "C5:NEW"     — дополнительная воронка (CATEGORY_ID = 5)

Здесь же лежат короткие STATUS_ID, которые использует бот. Если в портале
переименовали/пересобрали воронку — правим только этот файл.
"""

from __future__ import annotations

# --- Короткие STATUS_ID (без префикса категории) ---

STATUS_INCOMING = "NEW"           # входящая заявка (клиент нажал /start)
STATUS_AFTER_FIRST_PING = "UC_F3ZLGB"  # отправлено авто-сообщение #1, ждём ответ
STATUS_UNAVAILABLE = "UC_6OBDV3"  # бот заблокирован / чат недоступен
STATUS_REVISION = "UC_OMS9IC"     # отказ / недоставка / ревизия
STATUS_FIRST_TOUCH = "PREPARATION"  # «1 касание» — клиент проявил активность

# Стадии, из которых любую активность клиента считаем поводом вернуть его
# в работу («1 касание»).
BAD_STATUS_IDS: frozenset[str] = frozenset(
    {
        STATUS_INCOMING,
        STATUS_AFTER_FIRST_PING,
        "UC_LX2TD7",
        "LOSE",
        "UC_R1NGXP",
        STATUS_REVISION,
        STATUS_UNAVAILABLE,
        "UC_ARYLDU",
    }
)


def status_from_stage_id(stage_id: str | None) -> str:
    """'C5:UC_OERKGY' -> 'UC_OERKGY'; 'LOSE' -> 'LOSE'."""
    s = (stage_id or "").strip()
    if ":" in s:
        return s.split(":", 1)[1].strip()
    return s


def build_stage_id(category_id: int | str | None, status_id: str) -> str:
    """Собирает полный STAGE_ID с учётом воронки."""
    try:
        cid = int(category_id or 0)
    except (TypeError, ValueError):
        cid = 0
    return f"C{cid}:{status_id}" if cid > 0 else status_id


def stage_id_for_deal(deal: dict, status_id: str) -> str:
    """Полный STAGE_ID для конкретной сделки (берёт её CATEGORY_ID)."""
    if ":" in status_id:
        return status_id
    return build_stage_id(deal.get("CATEGORY_ID"), status_id)
