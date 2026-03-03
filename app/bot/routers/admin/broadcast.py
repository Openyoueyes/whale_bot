# app/bot/routers/admin/broadcast.py

from __future__ import annotations

from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext

from app.bot.keyboards.common import cancel_inline_kb
from app.integrations.bitrix.client import BitrixClient
from app.services.broadcast_service import (
    BroadcastScope,
    collect_recipients,
    send_message_broadcast,
)
from app.bot.filters.admin import AdminFilter
from app.services.message_formatters import format_message_for_bitrix

router = Router(name="admin-broadcast")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

bitrix_client = BitrixClient()


class BroadcastStates(StatesGroup):
    choosing_scope = State()
    choosing_pipeline = State()
    choosing_stage = State()

    choosing_button_mode = State()  # ✅ новый шаг: кнопка теста или нет
    entering_message = State()       # одно состояние для любого типа контента


def _scope_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Все воронки и стадии", callback_data="broadcast_scope:all")],
            [InlineKeyboardButton(text="🧭 По воронке", callback_data="broadcast_scope:pipeline")],
            [InlineKeyboardButton(text="🎯 По стадии", callback_data="broadcast_scope:stage")],
        ]
    )


def _button_mode_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Как есть (сохранить кнопки как в сообщении)", callback_data="broadcast_btn:keep")],
            [InlineKeyboardButton(text="➕ Добавить кнопку теста", callback_data="broadcast_btn:add_quiz")],
            [InlineKeyboardButton(text="➖ Убрать inline-кнопки", callback_data="broadcast_btn:remove")],
        ]
    )


async def _ask_button_mode(message_or_callback_message: Message, state: FSMContext) -> None:
    """
    Единый шаг после выбора охвата:
    спрашиваем режим (кнопка теста / как есть / убрать).
    """
    await state.set_state(BroadcastStates.choosing_button_mode)
    await message_or_callback_message.answer(
        "Выберите, что делать с кнопками в рассылке:\n\n"
        "✅ Как есть — рассылка 1:1 (кнопки сохранятся если были)\n"
        "➕ Добавить кнопку теста — всем поставим кнопку «Пройти тест»\n"
        "➖ Убрать — снимем любые inline-кнопки\n\n"
        "Отмена — кнопкой ниже.",
        reply_markup=cancel_inline_kb(),
    )
    await message_or_callback_message.answer("Режим кнопок:", reply_markup=_button_mode_kb())


@router.message(Command("broadcast"))
async def cmd_broadcast_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(BroadcastStates.choosing_scope)

    await message.answer(
        "Выберите охват рассылки.\n\n"
        "Отмена — кнопкой ниже.",
        reply_markup=cancel_inline_kb(),
    )
    await message.answer(
        "Кликните на нужный вариант:",
        reply_markup=_scope_kb(),
    )


@router.callback_query(
    BroadcastStates.choosing_scope,
    F.data.startswith("broadcast_scope:"),
)
async def choose_scope(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if not callback.message:
        await state.clear()
        return

    _, _, scope_raw = callback.data.partition("broadcast_scope:")

    # 1) Все воронки и стадии
    if scope_raw == "all":
        await state.update_data(scope=BroadcastScope.ALL.value, category_id=None, stage_id=None)
        # ✅ вместо entering_message -> спрашиваем режим кнопок
        await _ask_button_mode(callback.message, state)
        return

    # 2) По воронке
    if scope_raw == "pipeline":
        await state.update_data(scope=BroadcastScope.PIPELINE.value, stage_id=None)
        await state.set_state(BroadcastStates.choosing_pipeline)

        try:
            categories = await bitrix_client.list_categories()
        except Exception:
            categories = None

        if not categories:
            await state.clear()
            await callback.message.answer("Не удалось получить список воронок из Bitrix. Попробуйте позже.")
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"{c['NAME']} (ID {c['ID']})", callback_data=f"broadcast_pipeline:{c['ID']}")]
                for c in categories
            ]
        )

        await callback.message.answer(
            "Режим: 🧭 рассылка по воронке.\n\n"
            "1) Выберите воронку ниже.\n"
            "2) Затем выберите режим кнопок.\n"
            "3) Затем отправьте сообщение рассылки (любой тип).\n\n"
            "Отмена — кнопкой ниже.",
            reply_markup=cancel_inline_kb(),
        )
        await callback.message.answer("Список воронок:", reply_markup=kb)
        return

    # 3) По стадии в выбранной воронке
    if scope_raw == "stage":
        await state.update_data(scope=BroadcastScope.STAGE.value)
        await state.set_state(BroadcastStates.choosing_pipeline)

        try:
            categories = await bitrix_client.list_categories()
        except Exception:
            categories = None

        if not categories:
            await state.clear()
            await callback.message.answer("Не удалось получить список воронок из Bitrix. Попробуйте позже.")
            return

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"{c['NAME']} (ID {c['ID']})",
                    callback_data=f"broadcast_pipeline_for_stage:{c['ID']}",
                )]
                for c in categories
            ]
        )

        await callback.message.answer(
            "Режим: 🎯 рассылка по стадии.\n\n"
            "1) Выберите воронку.\n"
            "2) Выберите стадию.\n"
            "3) Затем выберите режим кнопок.\n"
            "4) Отправьте сообщение рассылки (любой тип).\n\n"
            "Отмена — кнопкой ниже.",
            reply_markup=cancel_inline_kb(),
        )
        await callback.message.answer("Список воронок:", reply_markup=kb)
        return

    await state.clear()
    await callback.message.answer("Неизвестный режим рассылки. Запустите заново: /broadcast")


@router.callback_query(
    BroadcastStates.choosing_pipeline,
    F.data.startswith("broadcast_pipeline:"),
)
async def choose_pipeline_for_pipeline(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if not callback.message:
        await state.clear()
        return

    _, _, id_str = callback.data.partition("broadcast_pipeline:")

    try:
        category_id = int(id_str)
    except ValueError:
        await state.clear()
        await callback.message.answer("Некорректный ID воронки. Запустите заново: /broadcast")
        return

    await state.update_data(category_id=category_id, stage_id=None)

    # ✅ спрашиваем режим кнопок
    await callback.message.answer(f"Охват: воронка ID={category_id}.")
    await _ask_button_mode(callback.message, state)


@router.callback_query(
    BroadcastStates.choosing_pipeline,
    F.data.startswith("broadcast_pipeline_for_stage:"),
)
async def choose_pipeline_for_stage(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if not callback.message:
        await state.clear()
        return

    _, _, id_str = callback.data.partition("broadcast_pipeline_for_stage:")

    try:
        category_id = int(id_str)
    except ValueError:
        await state.clear()
        await callback.message.answer("Некорректный ID воронки. Запустите заново: /broadcast")
        return

    await state.update_data(category_id=category_id)
    await state.set_state(BroadcastStates.choosing_stage)

    try:
        stages = await bitrix_client.list_stages(category_id)
    except Exception:
        stages = None

    if not stages:
        await state.clear()
        await callback.message.answer("Не удалось получить список стадий. Попробуйте позже.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(
                text=f"{s['NAME']} ({s['STATUS_ID']})",
                callback_data=f"broadcast_stage:{s['STATUS_ID']}",
            )]
            for s in stages
        ]
    )

    await callback.message.answer(
        f"Выбрана воронка ID={category_id}.\n"
        "Теперь выберите стадию:",
        reply_markup=kb,
    )
    await callback.message.answer(
        "Отмена — кнопкой ниже.",
        reply_markup=cancel_inline_kb(),
    )


@router.callback_query(
    BroadcastStates.choosing_stage,
    F.data.startswith("broadcast_stage:"),
)
async def choose_stage(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if not callback.message:
        await state.clear()
        return

    _, _, stage_id = callback.data.partition("broadcast_stage:")
    if not stage_id:
        await state.clear()
        await callback.message.answer("Некорректная стадия. Запустите заново: /broadcast")
        return

    await state.update_data(stage_id=stage_id)

    data = await state.get_data()
    category_id = data.get("category_id")

    await callback.message.answer(f"Охват: стадия {stage_id} в воронке ID={category_id}.")

    # ✅ спрашиваем режим кнопок
    await _ask_button_mode(callback.message, state)


@router.callback_query(
    BroadcastStates.choosing_button_mode,
    F.data.startswith("broadcast_btn:"),
)
async def choose_button_mode(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    if not callback.message:
        await state.clear()
        return

    _, _, mode_raw = callback.data.partition("broadcast_btn:")

    # в broadcast_service:
    # None = keep
    # "add" = add quiz
    # "remove" = remove
    quiz_button_mode = None
    if mode_raw == "add_quiz":
        quiz_button_mode = "add"
    elif mode_raw == "remove":
        quiz_button_mode = "remove"
    elif mode_raw == "keep":
        quiz_button_mode = None
    else:
        await state.clear()
        await callback.message.answer("Неизвестный режим кнопок. Запустите заново: /broadcast")
        return

    await state.update_data(quiz_button_mode=quiz_button_mode)
    await state.set_state(BroadcastStates.entering_message)

    human = "как есть (сохранить)" if quiz_button_mode is None else ("добавить кнопку теста" if quiz_button_mode == "add" else "убрать кнопки")
    await callback.message.answer(
        f"Режим кнопок: {human}.\n\n"
        "Теперь отправьте сообщение для рассылки (любой тип: текст/фото/видео/voice/файл и т.д.).\n\n"
        "Отмена — кнопкой ниже.",
        reply_markup=cancel_inline_kb(),
    )


@router.message(BroadcastStates.entering_message)
async def handle_broadcast_message(message: Message, state: FSMContext):
    data = await state.get_data()

    scope_raw = data.get("scope")
    try:
        scope = BroadcastScope(scope_raw)
    except Exception:
        await state.clear()
        await message.answer("Состояние рассылки повреждено. Запустите заново: /broadcast")
        return

    category_id: Optional[int] = data.get("category_id")
    stage_id: Optional[str] = data.get("stage_id")

    quiz_button_mode = data.get("quiz_button_mode")  # None | "add" | "remove"

    try:
        recipients = await collect_recipients(scope, category_id=category_id, stage_id=stage_id)
    except Exception:
        recipients = []

    if not recipients:
        await state.clear()
        await message.answer("Получателей не найдено — рассылка не выполнена.")
        return

    await message.answer(f"Запускаю рассылку. Получателей: {len(recipients)}.")

    try:
        bitrix_body = format_message_for_bitrix(message)

        stats = await send_message_broadcast(
            bot=message.bot,
            recipients=recipients,
            from_chat_id=message.chat.id,
            message_id=message.message_id,

            # твой режим кнопки (добавим ниже, если ты введёшь его в FSM)
            quiz_button_mode=data.get("quiz_button_mode"),
            quiz_button_text=data.get("quiz_button_text") or "🎯 Пройти тест",

            # ✅ вот это главное
            bitrix_message_body=bitrix_body,
        )
    except Exception:
        await state.clear()
        await message.answer("Ошибка при отправке рассылки. Попробуйте позже.")
        return

    await state.clear()
    await message.answer(
        "Рассылка завершена.\n"
        f"Успешно: {stats.get('sent', 0)}\n"
        f"Ошибок: {stats.get('failed', 0)}"
    )