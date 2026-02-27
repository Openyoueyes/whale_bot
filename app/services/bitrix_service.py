# app/services/bitrix_service.py

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, Any, List, Tuple

from aiogram import Bot

from app.config import (
    ADMIN_IDS,
    GROUP_CHAT_MESSAGES_ID,
    BITRIX_FIELD_TG_USERNAME_LEAD,
)
from app.integrations.bitrix.client import BitrixClient

bitrix_client = BitrixClient()


def _origin_label(origin: str) -> str:
    origin = (origin or "").strip().lower()
    if origin in ("business", "tg_business", "telegram_business"):
        return "Telegram Business"
    return "Telegram Bot"


def _pick_primary_lead(leads: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Выбираем "основной" лид: самый ранний/минимальный ID.
    Это важно, если из-за гонки появилось несколько лидов.
    """
    # в Bitrix ID строка -> приводим к int
    return sorted(leads, key=lambda x: int(x["ID"]))[0]


async def sync_user_with_bitrix_on_start(
    bot: Bot,
    user_info: Dict[str, Any],
    tag_value: str | None,
    is_first_visit: bool,
    *,
    silent: bool = False,
    origin: str = "bot",
) -> tuple[int | None, str | None]:
    tg_user_id = int(user_info["id"])
    if tg_user_id in ADMIN_IDS:
        return None, None

    origin_text = _origin_label(origin)

    # 1) Первая проверка
    try:
        existing_leads: List[Dict[str, Any]] = await bitrix_client.list_leads_by_telegram_id(
            telegram_id=tg_user_id
        )
    except Exception:
        existing_leads = []

    lead_id: int | None = None
    deal_id: str | None = None

    # ---------------------------------------------------------------------
    # ДОП ЗАЩИТА №1: если лидов нет и это first_visit -> повторная проверка
    # ---------------------------------------------------------------------
    if not existing_leads and is_first_visit:
        # небольшой yield, чтобы дать шанс другому параллельному обработчику закончить create_lead
        await asyncio.sleep(0)

        try:
            existing_leads = await bitrix_client.list_leads_by_telegram_id(telegram_id=tg_user_id)
        except Exception:
            existing_leads = []

        if not existing_leads:
            # -----------------------------------------------------------------
            # ДОП ЗАЩИТА №2: создаём лид, но сразу после — перепроверяем дубль
            # -----------------------------------------------------------------
            try:
                lead_resp = await bitrix_client.create_lead(
                    user_info,
                    tag_value,
                    origin=origin,
                )
            except Exception:
                lead_resp = {}

            lead_id_raw = lead_resp.get("result")
            created_lead_id = int(lead_id_raw) if lead_id_raw is not None else None

            # После создания подождём чуть-чуть и проверим, не появилось ли несколько лидов
            await asyncio.sleep(0.3)

            try:
                leads_after_create = await bitrix_client.list_leads_by_telegram_id(telegram_id=tg_user_id)
            except Exception:
                leads_after_create = []

            if leads_after_create:
                primary = _pick_primary_lead(leads_after_create)
                lead_id = int(primary["ID"])
            else:
                lead_id = created_lead_id

            # 2) Пытаемся получить сделку (по lead_id)
            deal_id = None
            deal_link_text = "Сделка ещё не создана"
            responsible_text = "не назначен"

            if lead_id is not None:
                deal_id, deal_link_text = await _fill_deal_fields_and_get_link(
                    lead_id=lead_id,
                    user_info=user_info,
                    tag_value=tag_value,
                )

                # Метка источника + ответственный + фиксация дублей
                if deal_id:
                    try:
                        await bitrix_client.add_deal_timeline_comment(
                            deal_id,
                            f"✅ Создан лид/сделка из источника: <b>{origin_text}</b>",
                        )

                        # ответственный по сделке
                        deal = await bitrix_client.get_deal(deal_id)
                        assigned_id = deal.get("ASSIGNED_BY_ID")

                        if assigned_id:
                            u = await bitrix_client.get_user(assigned_id)
                            first = (u.get("NAME") or "").strip()
                            last = (u.get("LAST_NAME") or "").strip()
                            login = (u.get("LOGIN") or "").strip()
                            full = (first + " " + last).strip()
                            responsible_text = full or login or str(assigned_id)

                    except Exception:
                        # оставляем responsible_text = "не назначен"
                        pass

                    # Если из-за гонки всё же было создано несколько лидов — зафиксируем это в сделке
                    if len(leads_after_create) > 1:
                        try:
                            dup_ids = ", ".join(sorted({str(x["ID"]) for x in leads_after_create}))
                            await bitrix_client.add_deal_timeline_comment(
                                deal_id,
                                "⚠️ Обнаружены дубли лидов по TG_ID (гонка сообщений).\n"
                                f"Список lead_id: <code>{dup_ids}</code>\n"
                                f"Выбран основной lead_id: <code>{lead_id}</code>",
                            )
                        except Exception:
                            pass

            # 3) Уведомление в группу (если не silent)
            if not silent:
                current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                message_text = (
                    "Создан новый лид!\n"
                    "----------------------------------------------------------\n"
                    f"{deal_link_text}\n"
                    "----------------------------------------------------------\n"
                    f"Источник: {origin_text}\n"
                    f"Имя и фамилия: {user_info.get('first_name', 'имя не указано')} "
                    f"{user_info.get('last_name', 'фамилия не указана')}\n"
                    f"TG Username: @{user_info.get('username', 'нет username')}\n"
                    f"TG ID: {str(user_info.get('id', 'ошибка получения id'))}\n"
                    f"Тег: {tag_value or 'нет тега'}\n"
                    f"Дата и время создания: {current_datetime}\n"
                    f"Ответственный: {responsible_text}"
                )

                if GROUP_CHAT_MESSAGES_ID:
                    try:
                        await bot.send_message(
                            GROUP_CHAT_MESSAGES_ID,
                            message_text,
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                        )
                    except Exception:
                        pass

            return lead_id, deal_id

        # Если на повторной проверке лид уже появился — просто продолжаем ниже

    # ---------------------------------------------------------------------
    # ДАЛЬШЕ: “лиды уже есть”
    # ---------------------------------------------------------------------
    if existing_leads:
        primary = _pick_primary_lead(existing_leads)
        lead_id = int(primary["ID"])

    # обновление username (как у вас)
    new_username = user_info.get("username")
    if new_username and existing_leads:
        for lead in existing_leads:
            old_username = (
                lead.get(BITRIX_FIELD_TG_USERNAME_LEAD)
                or lead.get("Telegram Username")
            )
            if old_username != new_username:
                try:
                    await bitrix_client.update_lead_username(lead["ID"], new_username)
                except Exception:
                    pass

    # ищем сделку по lead_id
    if lead_id is not None:
        try:
            deals = await bitrix_client.list_deals_by_lead_id(lead_id)
            if deals:
                deal_id = str(deals[0]["ID"])
        except Exception:
            pass

    return lead_id, deal_id


async def _fill_deal_fields_and_get_link(
        lead_id: int,
        user_info: Dict[str, Any],
        tag_value: str | None,
        attempts: int = 5,
        delay: float = 2.0,
) -> tuple[str | None, str]:
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
                pass

            deal_link = bitrix_client.make_deal_link(deal_id)
            return deal_id, f'<a href="{deal_link}">Ссылка на сделку</a>'

        await asyncio.sleep(delay)

    return None, "Сделка ещё не создана"
