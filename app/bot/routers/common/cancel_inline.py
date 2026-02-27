from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext

router = Router(name="common-cancel-inline")

@router.callback_query(StateFilter("*"), F.data == "fsm:cancel")
async def cancel_fsm_inline(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    # убираем клавиатуру у сообщения, где была кнопка отмены
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await cb.answer("Отменено")
    try:
        await cb.message.answer("Ок, отменено.")
    except Exception:
        pass