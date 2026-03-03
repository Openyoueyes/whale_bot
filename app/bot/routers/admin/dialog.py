# app/bot/routers/admin/dialog.py

from __future__ import annotations

from typing import Optional, Tuple

from aiogram import Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app.bot.filters.admin import AdminFilter
from app.bot.keyboards.common import cancel_inline_kb
from app.integrations.bitrix.client import BitrixClient
from app.services.dialog_service import _format_message_for_bitrix

router = Router(name="admin-dialog")

router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

bitrix_client = BitrixClient()

MANAGER_PREFIX = "Менеджер WhaleTrade ответил:\n\n"


class AdminDialogStates(StatesGroup):
    replying_to_client = State()
    direct_send_waiting_tg_id = State()
    direct_send_waiting_content = State()  # одно состояние для любого типа


def _extract_text_or_caption(message: Message) -> str:
    """
    Возвращает текст (для text) или caption (для медиа), иначе пустую строку.
    """
    if message.text:
        return message.text
    if message.caption:
        return message.caption
    return ""


def _has_caption_capability(message: Message) -> bool:
    """
    Условно: есть ли у сообщения caption-поле (photo/video/document/animation/audio)
    Технически caption может быть у многих типов, но на практике:
    - voice/video_note/sticker не имеют caption.
    """
    return bool(message.photo or message.video or message.document or message.animation or message.audio)


async def _send_with_manager_prefix(
    *,
    bot,
    admin_message: Message,
    target_chat_id: int,
) -> Tuple[bool, str]:
    """
    Универсальная отправка "как менеджер" с префиксом.
    Возвращает (ok, log_text_for_bitrix)

    Логика:
    - Если это текст -> отправляем новый текст с префиксом
    - Если медиа с caption -> копируем сообщение, но сначала меняем caption нельзя при copy_message.
      Поэтому: отправляем префикс отдельным сообщением + копируем медиа как есть,
      ИЛИ: переслать с новым caption можно только через resend (download not allowed) -> не делаем.
      Компромисс: если есть caption, отправляем отдельное сообщение с префиксом+caption, затем копию медиа.
    - Если медиа без caption -> отправляем префикс отдельным сообщением, затем копию медиа
    """
    prefix = MANAGER_PREFIX
    body = _extract_text_or_caption(admin_message)

    # Текстовое сообщение
    if admin_message.text:
        outgoing_text = f"{prefix}{body}"
        await bot.send_message(
            chat_id=target_chat_id,
            text=outgoing_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True, outgoing_text

    # Любой НЕ-текст (фото/видео/voice/док/стикер/кружок/и т.д.)
    # 1) Сначала отдельным сообщением префикс (и caption/описание если было)
    if body:
        meta_text = f"{prefix}{body}"
    else:
        meta_text = f"{prefix}(медиа)"

    await bot.send_message(
        chat_id=target_chat_id,
        text=meta_text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    # 2) Затем копируем оригинал 1-в-1 (универсально)
    await bot.copy_message(
        chat_id=target_chat_id,
        from_chat_id=admin_message.chat.id,
        message_id=admin_message.message_id,
    )

    return True, meta_text


# ---------- ОТВЕТ ПО КНОПКЕ "Ответить клиенту" ----------

@router.callback_query(F.data.startswith("reply_to_client:"))
async def start_reply_to_client(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if not callback.message:
        return

    _, _, payload = callback.data.partition("reply_to_client:")
    try:
        tg_id_str, deal_part = payload.split(":", 1)
    except ValueError:
        await callback.message.answer("Некорректные данные для ответа клиенту.")
        return

    try:
        tg_id = int(tg_id_str)
    except ValueError:
        await callback.message.answer("Некорректный Telegram ID клиента.")
        return

    deal_id: Optional[str] = None if deal_part == "no_deal" else deal_part

    await state.set_state(AdminDialogStates.replying_to_client)
    await state.update_data(reply_tg_id=tg_id, reply_deal_id=deal_id)

    await callback.message.answer(
        f"Ответ клиенту (TG ID: {tg_id}).\n"
        f"Отправьте сообщение (любой тип: текст/фото/видео/voice/документ и т.д.).\n\n"
        f"Отмена — кнопкой ниже.",
        reply_markup=cancel_inline_kb(),
    )


@router.message(StateFilter(AdminDialogStates.replying_to_client))
async def send_reply_to_client(message: Message, state: FSMContext):
    data = await state.get_data()
    if "reply_tg_id" not in data:
        await message.answer("Не удалось определить клиента для ответа. Попробуйте ещё раз.")
        await state.clear()
        return

    tg_id: int = data["reply_tg_id"]
    deal_id: Optional[str] = data.get("reply_deal_id")

    # Отправляем клиенту с префиксом + универсальной поддержкой типов
    try:
        ok, log_text = await _send_with_manager_prefix(
            bot=message.bot,
            admin_message=message,
            target_chat_id=tg_id,
        )
    except Exception:
        await message.answer("Не удалось отправить сообщение клиенту (возможно, бот заблокирован).")
        await state.clear()
        return

    # Лог в Bitrix
    if deal_id and ok:
        # логируем более информативно:
        # - если текст -> сам текст с префиксом
        # - если медиа -> meta_text (префикс + caption/медиа)
        comment = (
            "Ответ менеджера из Telegram бота:\n\n"
            f"{log_text}"
        )
        try:
            await bitrix_client.add_deal_timeline_comment(deal_id, comment)
        except Exception:
            pass

    await message.answer("Ответ отправлен клиенту.")
    await state.clear()


# ---------- /send_to: ОТПРАВИТЬ ПО TG ID (любой тип) ----------

@router.message(Command("send_to"))
async def cmd_send_to(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(AdminDialogStates.direct_send_waiting_tg_id)
    await message.answer(
        "Введите Telegram ID клиента, которому нужно отправить сообщение.\n"
        "Пример: 8129274236\n\n"
        "Отмена — кнопкой ниже.",
        reply_markup=cancel_inline_kb(),
    )


@router.message(StateFilter(AdminDialogStates.direct_send_waiting_tg_id))
async def get_tg_id_for_direct_send(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    try:
        tg_id = int(raw)
    except ValueError:
        await message.answer("Некорректный Telegram ID. Введите только число.")
        return

    await state.update_data(direct_tg_id=tg_id)
    await state.set_state(AdminDialogStates.direct_send_waiting_content)
    await message.answer(
        "Теперь отправьте сообщение клиенту (любой тип: текст/фото/видео/voice/документ/кружок и т.д.).\n\n"
        "Отмена — кнопкой ниже.",
        reply_markup=cancel_inline_kb(),
    )


@router.message(StateFilter(AdminDialogStates.direct_send_waiting_content))
async def send_direct_to_client(message: Message, state: FSMContext):
    data = await state.get_data()

    tg_id = data.get("direct_tg_id")
    if not tg_id:
        await message.answer("Не удалось определить Telegram ID клиента. Попробуйте ещё раз.")
        await state.clear()
        return

    # 1) Отправляем клиенту с префиксом (любой тип)
    try:
        ok, log_text = await _send_with_manager_prefix(
            bot=message.bot,
            admin_message=message,
            target_chat_id=int(tg_id),
        )
    except Exception:
        await message.answer("Не удалось отправить сообщение клиенту (возможно, бот заблокирован).")
        await state.clear()
        return

    # 2) Логируем в Bitrix (если найдется сделка)
    try:
        deal = await bitrix_client.find_deal_for_telegram_user(int(tg_id))
    except Exception:
        deal = None

    if deal and ok:
        deal_id = deal["ID"]
        comment = (
            "Исходящее сообщение менеджера из Telegram бота "
            "(по команде /send_to):\n\n"
            f"{log_text}"
        )
        try:
            await bitrix_client.add_deal_timeline_comment(deal_id, comment)
        except Exception:
            pass

    await message.answer("Сообщение отправлено клиенту.")
    await state.clear()