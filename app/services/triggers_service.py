from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import Message

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession



from app.db.models import TriggerReply


def normalize_keyword(s: str) -> str:
    return (s or "").strip().lower()


async def get_trigger_by_keyword(session: AsyncSession, keyword: str) -> Optional[TriggerReply]:
    kw = normalize_keyword(keyword)
    if not kw:
        return None
    res = await session.execute(select(TriggerReply).where(TriggerReply.keyword == kw))
    return res.scalar_one_or_none()


async def list_triggers(session: AsyncSession) -> list[TriggerReply]:
    res = await session.execute(select(TriggerReply).order_by(TriggerReply.id.desc()))
    return list(res.scalars().all())


async def delete_trigger(session: AsyncSession, keyword: str) -> bool:
    tr = await get_trigger_by_keyword(session, keyword)
    if not tr:
        return False
    await session.delete(tr)
    return True


async def set_trigger_enabled(session: AsyncSession, keyword: str, enabled: bool) -> bool:
    tr = await get_trigger_by_keyword(session, keyword)
    if not tr:
        return False
    tr.is_enabled = bool(enabled)
    tr.updated_at = datetime.utcnow()
    return True


def _extract_trigger_content_from_message(message: Message) -> tuple[str, str | None, Dict[str, Any]]:
    """
    Возвращает (content_type, text, payload)
    """
    text = (message.text or message.caption or None)

    if message.photo:
        # берем самое большое фото
        file_id = message.photo[-1].file_id
        return "photo", text, {"file_id": file_id}

    if message.video:
        return "video", text, {"file_id": message.video.file_id}

    if message.document:
        return "document", text, {
            "file_id": message.document.file_id,
            "file_name": message.document.file_name,
        }

    if message.voice:
        return "voice", text, {"file_id": message.voice.file_id}

    if message.audio:
        return "audio", text, {"file_id": message.audio.file_id}

    if message.sticker:
        return "sticker", None, {"file_id": message.sticker.file_id}

    # fallback
    return "text", (text or ""), {}


async def upsert_trigger_from_message(
    session: AsyncSession,
    *,
    keyword: str,
    title: str | None,
    sample_message: Message,
) -> TriggerReply:
    kw = normalize_keyword(keyword)
    content_type, text, payload = _extract_trigger_content_from_message(sample_message)

    tr = await get_trigger_by_keyword(session, kw)
    if tr:
        tr.title = title
        tr.content_type = content_type
        tr.text = text
        tr.payload = payload
        tr.is_enabled = True
        tr.updated_at = datetime.utcnow()
        return tr

    tr = TriggerReply(
        keyword=kw,
        title=title,
        is_enabled=True,
        content_type=content_type,
        text=text,
        payload=payload,
    )
    session.add(tr)
    return tr


async def send_trigger_reply(bot: Bot, chat_id: int, trigger: TriggerReply) -> None:
    """
    Отправка сохраненного ответа клиенту.
    """
    ct = trigger.content_type
    text = trigger.text
    payload = trigger.payload or {}

    if ct == "text":
        await bot.send_message(chat_id, text or "")
        return

    if ct == "photo":
        await bot.send_photo(chat_id, photo=payload["file_id"], caption=text)
        return

    if ct == "video":
        await bot.send_video(chat_id, video=payload["file_id"], caption=text)
        return

    if ct == "document":
        await bot.send_document(chat_id, document=payload["file_id"], caption=text)
        return

    if ct == "voice":
        await bot.send_voice(chat_id, voice=payload["file_id"], caption=text)
        return

    if ct == "audio":
        await bot.send_audio(chat_id, audio=payload["file_id"], caption=text)
        return

    if ct == "sticker":
        await bot.send_sticker(chat_id, sticker=payload["file_id"])
        return

    # fallback
    await bot.send_message(chat_id, text or "")