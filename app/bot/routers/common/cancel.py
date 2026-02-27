# app/bot/routers/common/cancel.py

from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

router = Router(name="common-cancel")


@router.message(Command("cancel"))
@router.message(F.text.in_({"Отмена", "❌ Отмена"}))
async def cancel_any_state(message: Message, state: FSMContext):
    current_state = await state.get_state()

    if current_state is None:
        await message.answer("Сейчас нет активного действия, которое можно отменить.")
        return

    await state.clear()
    await message.answer("Текущее действие отменено.")
