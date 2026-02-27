# app/bot/routers/client/manager.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message

from app.bot.keyboards.manager import get_manager_keyboard
from app.config import MANAGER_CONTACT_IMAGE_FILE_ID
from app.db.session import async_session_maker
from app.db.queries import get_active_manager

router = Router(name="client-manager")

def _normalize_tg_link(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("http://") or s.startswith("https://"):
        return s
    if s.startswith("@"):
        return f"https://t.me/{s[1:]}"
    # если просто username
    return f"https://t.me/{s}"

@router.message(F.text == "📞 Связь с менеджером")
async def manager_entry(message: Message):
    async with async_session_maker() as session:
        mgr = await get_active_manager(session)

    if not mgr:
        await message.answer("Сейчас менеджер не назначен. Напишите позже или в поддержку.")
        return

    url = _normalize_tg_link(mgr.tg_link)
    if not url:
        await message.answer("Контакт менеджера не настроен. Сообщите администратору.")
        return

    # Минимальный текст (можешь вообще пустым сделать, но лучше 1 строка)
    text = f"Связь с менеджером: <b>{mgr.name}</b>"

    if MANAGER_CONTACT_IMAGE_FILE_ID:
        await message.answer_photo(
            photo=MANAGER_CONTACT_IMAGE_FILE_ID,
            caption=text,
            reply_markup=get_manager_keyboard(url),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            text,
            reply_markup=get_manager_keyboard(url),
            parse_mode="HTML",
            disable_web_page_preview=True,
        )