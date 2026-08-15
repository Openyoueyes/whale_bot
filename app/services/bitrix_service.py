# app/services/bitrix_service.py

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from aiogram import Bot

from app.config import ADMIN_IDS, BITRIX_FIELD_TG_USERNAME_LEAD
from app.integrations.bitrix.client import BitrixClient
from app.services.bitrix_presenter import build_deal_card
from app.services.locks import client_lock
from app.services.notify_service import notify_leads_group

logger = logging.getLogger(__name__)

bitrix_client = BitrixClient()


def _origin_label(origin: str) -> str:
    origin = (origin or "").strip().lower()
    if origin in ("business", "tg_business", "telegram_business"):
        return "Telegram Business"
    return "Telegram Bot"


def _pick_primary_lead(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    «Основной» лид — с минимальным ID. Важно, если из-за гонки
    или ручного заведения в CRM лидов оказалось несколько.
    """
    return sorted(leads, key=lambda x: int(x["ID"]))[0]


async def _safe_list_leads(tg_user_id: int) -> List[Dict[str, Any]]:
    try:
        return await bitrix_client.list_leads_by_telegram_id(telegram_id=tg_user_id)
    except Exception:
        logger.warning("Не удалось получить лиды по tg_id=%s", tg_user_id)
        return []


async def sync_user_with_bitrix_on_start(
    bot: Bot,
    user_info: Dict[str, Any],
    tag_value: str | None,
    is_first_visit: bool,
    *,
    silent: bool = False,
    origin: str = "bot",
) -> Tuple[Optional[int], Optional[str]]:
    """
    Приводит Bitrix в соответствие с состоянием клиента: лид есть, сделка найдена,
    UF-поля заполнены. Возвращает (lead_id, deal_id).

    Обработка одного клиента сериализована локом: два быстрых /start подряд
    больше не могут создать два лида.

    is_first_visit влияет только на текст уведомления. Решение «создавать лид или
    нет» принимается по факту наличия лида в CRM: иначе клиент, у которого лид
    удалили вручную, навсегда оставался бы без сделки.
    """
    tg_user_id = int(user_info["id"])
    if tg_user_id in ADMIN_IDS:
        return None, None

    async with client_lock(tg_user_id):
        return await sync_user_with_bitrix_locked(
            bot=bot,
            user_info=user_info,
            tag_value=tag_value,
            is_first_visit=is_first_visit,
            silent=silent,
            origin=origin,
        )


async def sync_user_with_bitrix_locked(
    *,
    bot: Bot,
    user_info: Dict[str, Any],
    tag_value: str | None,
    is_first_visit: bool,
    silent: bool = False,
    origin: str = "bot",
) -> Tuple[Optional[int], Optional[str]]:
    """
    То же самое, но БЕЗ взятия лока: вызывать только когда client_lock(tg_id)
    уже удерживается вызывающим кодом (asyncio.Lock не реентрантный).
    """
    tg_user_id = int(user_info["id"])
    if tg_user_id in ADMIN_IDS:
        return None, None

    existing_leads = await _safe_list_leads(tg_user_id)

    if not existing_leads:
        return await _create_lead_flow(
            bot=bot,
            tg_user_id=tg_user_id,
            user_info=user_info,
            tag_value=tag_value,
            is_first_visit=is_first_visit,
            silent=silent,
            origin=origin,
        )

    # --- Лид уже есть ---
    lead_id = int(_pick_primary_lead(existing_leads)["ID"])

    await _refresh_lead_username(existing_leads, user_info.get("username"))

    deal_id: Optional[str] = None
    try:
        deals = await bitrix_client.list_deals_by_lead_id(lead_id)
        if deals:
            deal_id = str(deals[0]["ID"])
    except Exception:
        logger.warning("Не удалось получить сделки лида %s", lead_id)

    return lead_id, deal_id


async def _create_lead_flow(
    *,
    bot: Bot,
    tg_user_id: int,
    user_info: Dict[str, Any],
    tag_value: str | None,
    is_first_visit: bool,
    silent: bool,
    origin: str,
) -> Tuple[Optional[int], Optional[str]]:
    origin_text = _origin_label(origin)

    try:
        lead_resp = await bitrix_client.create_lead(user_info, tag_value, origin=origin)
    except Exception:
        logger.exception("Не удалось создать лид для tg_id=%s", tg_user_id)
        return None, None

    lead_id_raw = lead_resp.get("result")
    lead_id: Optional[int] = int(lead_id_raw) if lead_id_raw is not None else None

    # Лид могли завести параллельно (робот CRM, менеджер вручную) — перепроверяем.
    leads_after_create = await _safe_list_leads(tg_user_id)
    if leads_after_create:
        lead_id = int(_pick_primary_lead(leads_after_create)["ID"])

    if lead_id is None:
        return None, None

    deal_id, deal_link_text = await _fill_deal_fields_and_get_link(
        lead_id=lead_id,
        user_info=user_info,
        tag_value=tag_value,
    )

    responsible_text = "не назначен"

    if deal_id:
        try:
            await bitrix_client.add_deal_timeline_comment(
                deal_id,
                f"✅ Создан лид/сделка из источника: <b>{origin_text}</b>",
            )
        except Exception:
            logger.warning("Не удалось отметить источник в сделке %s", deal_id)

        try:
            card = await build_deal_card(await bitrix_client.get_deal(deal_id))
            responsible_text = card.responsible
        except Exception:
            logger.warning("Не удалось определить ответственного по сделке %s", deal_id)

        if len(leads_after_create) > 1:
            dup_ids = ", ".join(sorted({str(x["ID"]) for x in leads_after_create}))
            try:
                await bitrix_client.add_deal_timeline_comment(
                    deal_id,
                    "⚠️ Обнаружены дубли лидов по TG_ID.\n"
                    f"Список lead_id: <code>{dup_ids}</code>\n"
                    f"Выбран основной lead_id: <code>{lead_id}</code>",
                )
            except Exception:
                logger.warning("Не удалось записать дубли лидов в сделку %s", deal_id)

    if not silent:
        visit_text = "первый визит" if is_first_visit else "повторный визит"
        await notify_leads_group(
            bot,
            (
                "Создан новый лид!\n"
                "----------------------------------------------------------\n"
                f"{deal_link_text}\n"
                "----------------------------------------------------------\n"
                f"Источник: {origin_text} ({visit_text})\n"
                f"Имя и фамилия: {user_info.get('first_name', 'имя не указано')} "
                f"{user_info.get('last_name', 'фамилия не указана')}\n"
                f"TG Username: @{user_info.get('username', 'нет username')}\n"
                f"TG ID: {tg_user_id}\n"
                f"Тег: {tag_value or 'нет тега'}\n"
                f"Дата и время создания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Ответственный: {responsible_text}"
            ),
        )

    return lead_id, deal_id


async def _refresh_lead_username(leads: List[Dict[str, Any]], new_username: str | None) -> None:
    """Подтягиваем актуальный username в лиды, где он устарел."""
    if not new_username:
        return

    for lead in leads:
        old_username = lead.get(BITRIX_FIELD_TG_USERNAME_LEAD) or lead.get("Telegram Username")
        if old_username == new_username:
            continue
        try:
            await bitrix_client.update_lead_username(lead["ID"], new_username)
        except Exception:
            logger.warning("Не удалось обновить username лида %s", lead.get("ID"))


async def _fill_deal_fields_and_get_link(
    lead_id: int,
    user_info: Dict[str, Any],
    tag_value: str | None,
    attempts: int = 5,
    delay: float = 2.0,
) -> Tuple[Optional[str], str]:
    """
    Сделку из лида создаёт робот на стороне Bitrix, поэтому ждём её появления.
    """
    for _ in range(attempts):
        try:
            deals = await bitrix_client.list_deals_by_lead_id(lead_id)
        except Exception:
            deals = []

        if deals:
            deal_id = str(deals[0]["ID"])
            try:
                await bitrix_client.update_deal_fields_from_user(deal_id, user_info, tag_value)
            except Exception:
                logger.warning("Не удалось заполнить UF-поля сделки %s", deal_id)

            deal_link = bitrix_client.make_deal_link(deal_id)
            return deal_id, f'<a href="{deal_link}">Ссылка на сделку</a>'

        await asyncio.sleep(delay)

    return None, "Сделка ещё не создана"
