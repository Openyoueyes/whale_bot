# app/bot/routers/admin/triggers.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from html import escape as html_escape
from app.bot.filters.admin import AdminFilter
from app.bot.keyboards.triggers import _menu_kb
from app.db.session import async_session_maker
from app.services.triggers_service import (
    normalize_keyword,
    list_triggers,
    upsert_trigger_from_message,
    delete_trigger,
    set_trigger_enabled,
)

router = Router(name="admin-triggers")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024


def _is_caption_message(message: Message) -> bool:
    """
    Типы, которые реально поддерживают caption в Telegram:
    photo, video, document, animation, audio
    """
    return bool(message.photo or message.video or message.document or message.animation or message.audio)


def _content_length(message: Message) -> int:
    """
    Для text -> длина message.text
    Для медиа с caption -> длина message.caption
    Иначе 0
    """
    if message.text:
        return len(message.text)
    if message.caption:
        return len(message.caption)
    return 0
class TriggerStates(StatesGroup):
    waiting_keyword = State()
    waiting_title = State()
    waiting_content = State()




@router.message(Command("triggers"))
async def triggers_root(message: Message):
    await message.answer(
        "⚙️ <b>Триггер-ответы</b>\n\n"
        "• /triggers — меню\n"
        "• Можно сохранять любой ответ (текст/фото/видео/voice/файл и т.д.)\n"
        "• Клиент пишет ключевое слово → получает сохранённый ответ.\n",
        reply_markup=_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "triggers:list")
async def triggers_list(callback: CallbackQuery):
    await callback.answer()
    async with async_session_maker() as session:
        items = await list_triggers(session)

    if not items:
        await callback.message.answer("Список пуст.")
        return

    lines = ["📋 <b>Триггеры:</b>\n"]
    for t in items:
        status = "✅" if t.is_enabled else "⛔️"

        kw = html_escape(t.keyword or "")
        ctype = html_escape(t.content_type or "")
        title = html_escape(t.title) if t.title else ""

        title_part = f" — {title}" if title else ""
        lines.append(f'{status} <code>{kw}</code> ({ctype}){title_part}')

    lines.append(
        "\nКоманды:\n"
        "• <code>/trigger_on keyword</code>\n"
        "• <code>/trigger_off keyword</code>\n"
        "• <code>/trigger_del keyword</code>"
    )

    await callback.message.answer("\n".join(lines), parse_mode="HTML")

@router.callback_query(F.data == "triggers:add")
async def triggers_add_start(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.set_state(TriggerStates.waiting_keyword)
    await callback.message.answer(
        "Введите <b>ключевое слово</b> (например: <code>Советник</code>).\n"
        "Оно будет срабатывать по точному совпадению текста/подписи.",
        parse_mode="HTML",
    )


@router.message(StateFilter(TriggerStates.waiting_keyword))
async def triggers_add_keyword(message: Message, state: FSMContext):
    kw = normalize_keyword(message.text or "")
    if not kw:
        await message.answer("Пустое ключевое слово. Введите ещё раз.")
        return
    await state.update_data(keyword=kw)
    await state.set_state(TriggerStates.waiting_title)
    await message.answer(
        "Введите короткое <b>название</b> (можно пропустить, отправив <code>-</code>).",
        parse_mode="HTML",
    )


@router.message(StateFilter(TriggerStates.waiting_title))
async def triggers_add_title(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    title = None if raw == "-" else raw[:255]
    await state.update_data(title=title)
    await state.set_state(TriggerStates.waiting_content)
    await message.answer(
        "Теперь отправьте <b>сообщение-ответ</b>, которое получит клиент.\n"
        "Можно: текст, фото, видео, voice, документ, аудио, с подписью и т.д.",
        parse_mode="HTML",
    )


@router.message(StateFilter(TriggerStates.waiting_content))
async def triggers_add_content(message: Message, state: FSMContext):
    data = await state.get_data()
    kw = data["keyword"]
    title = data.get("title")

    # Определяем: это "текст" или "медиа+caption"
    is_caption = _is_caption_message(message)
    length = _content_length(message)

    # 1) Медиа + caption => лимит 1024
    if is_caption:
        if length > CAPTION_LIMIT:
            over = length - CAPTION_LIMIT
            await message.answer(
                "⛔️ <b>Триггер не сохранён</b>\n\n"
                "Вы отправили медиа с подписью, но подпись превышает лимит Telegram.\n\n"
                f"• Сейчас: <b>{length}</b> символов\n"
                f"• Лимит: <b>{CAPTION_LIMIT}</b>\n"
                f"• Нужно сократить минимум на: <b>{over}</b>\n\n"
                "Сократите текст подписи и отправьте сообщение заново.",
                parse_mode="HTML",
            )
            # Остаёмся в waiting_content (НЕ очищаем state)
            return

    # 2) Только текст => лимит 4096
    else:
        # Если это вообще не текст (например voice/sticker/video_note без caption),
        # то length будет 0 и проверка не мешает.
        if message.text and length > TEXT_LIMIT:
            over = length - TEXT_LIMIT
            await message.answer(
                "⛔️ <b>Триггер не сохранён</b>\n\n"
                "Текст превышает лимит Telegram для одного сообщения.\n\n"
                f"• Сейчас: <b>{length}</b> символов\n"
                f"• Лимит: <b>{TEXT_LIMIT}</b>\n"
                f"• Нужно сократить минимум на: <b>{over}</b>\n\n"
                "Сократите текст и отправьте сообщение заново.",
                parse_mode="HTML",
            )
            return

    # Если лимиты соблюдены — сохраняем триггер
    async with async_session_maker() as session:
        await upsert_trigger_from_message(
            session,
            keyword=kw,
            title=title,
            sample_message=message,
        )
        await session.commit()

    await state.clear()
    await message.answer(
        f"✅ Триггер сохранён: <code>{html_escape(kw)}</code>\n"
        f"Теперь клиент, написав <code>{html_escape(kw)}</code>, получит этот ответ.",
        parse_mode="HTML",
        reply_markup=_menu_kb(),
    )


@router.callback_query(F.data == "triggers:del")
async def triggers_delete_hint(callback: CallbackQuery):
    await callback.answer()
    await callback.message.answer(
        "Удаление: отправьте команду\n"
        "<code>/trigger_del ключевое_слово</code>\n"
        "Пример: <code>/trigger_del Советник</code>",
        parse_mode="HTML",
    )


@router.message(Command("trigger_del"))
async def cmd_trigger_del(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /trigger_del <keyword>")
        return
    kw = normalize_keyword(parts[1])

    async with async_session_maker() as session:
        ok = await delete_trigger(session, kw)
        await session.commit()

    await message.answer("✅ Удалён." if ok else "Не найдено.")


@router.message(Command("trigger_on"))
async def cmd_trigger_on(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /trigger_on <keyword>")
        return
    kw = normalize_keyword(parts[1])

    async with async_session_maker() as session:
        ok = await set_trigger_enabled(session, kw, True)
        await session.commit()

    await message.answer("✅ Включён." if ok else "Не найдено.")


@router.message(Command("trigger_off"))
async def cmd_trigger_off(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /trigger_off <keyword>")
        return
    kw = normalize_keyword(parts[1])

    async with async_session_maker() as session:
        ok = await set_trigger_enabled(session, kw, False)
        await session.commit()

    await message.answer("⛔️ Выключен." if ok else "Не найдено.")