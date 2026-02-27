# app/bot/routers/admin/change_manager.py
from __future__ import annotations

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app.bot.filters.admin import AdminFilter
from app.db.session import async_session_maker
from app.db.queries import list_managers, set_active_manager

router = Router(name="admin-change-manager")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())


class ChangeManagerStates(StatesGroup):
    choosing = State()


def _kb_managers(managers) -> InlineKeyboardMarkup:
    rows = []
    for m in managers:
        label = f"{'🟢 ' if m.is_active else ''}{m.name} (id={m.id})"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"cm:set:{m.id}")])
    rows.append([InlineKeyboardButton(text="⛔️ Отмена", callback_data="cm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("change_manager"))
async def cmd_change_manager(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ChangeManagerStates.choosing)

    async with async_session_maker() as session:
        managers = await list_managers(session)

    if not managers:
        await state.clear()
        await message.answer("В БД нет менеджеров. Сначала добавьте записи в current_manager.")
        return

    await message.answer(
        "Выберите, кто будет <b>текущим активным</b> менеджером:",
        reply_markup=_kb_managers(managers),
        parse_mode="HTML",
    )


@router.callback_query(ChangeManagerStates.choosing, F.data == "cm:cancel")
async def cm_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Отменено")
    await state.clear()
    if callback.message:
        await callback.message.answer("Ок, отменил.")


@router.callback_query(ChangeManagerStates.choosing, F.data.startswith("cm:set:"))
async def cm_set(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if not callback.message:
        await state.clear()
        return

    try:
        manager_id = int((callback.data or "").split(":")[-1])
    except Exception:
        await state.clear()
        await callback.message.answer("Некорректный выбор. Запустите заново: /change_manager")
        return

    async with async_session_maker() as session:
        ok = await set_active_manager(session, manager_id)
        if ok:
            await session.commit()
        else:
            await session.rollback()

        managers = await list_managers(session)

    if not ok:
        await state.clear()
        await callback.message.answer("Менеджер не найден. Запустите заново: /change_manager")
        return

    await state.clear()
    await callback.message.answer(
        "✅ Текущий менеджер обновлён.",
        reply_markup=_kb_managers(managers),
    )