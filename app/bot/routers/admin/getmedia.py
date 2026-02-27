from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.enums import ParseMode

from app.bot.filters.admin import AdminFilter
from app.bot.keyboards.getmedia import get_media_type_kb
from app.bot.keyboards.common import cancel_inline_kb

router = Router(name="admin-getmedia")
router.message.filter(AdminFilter())
router.callback_query.filter(AdminFilter())

ALLOWED_MEDIA_TYPES = {
    "photo", "video", "audio", "voice",
    "document", "sticker", "animation", "video_note",
}

class GetMediaStates(StatesGroup):
    choose_type = State()
    waiting_file_id = State()

@router.message(Command("getmedia"))
async def getmedia_start(message: Message, state: FSMContext):
    await state.set_state(GetMediaStates.choose_type)
    await message.answer("Выберите тип медиа:", reply_markup=get_media_type_kb())

@router.callback_query(GetMediaStates.choose_type, F.data.startswith("getmedia:type:"))
async def getmedia_choose_type(cb: CallbackQuery, state: FSMContext):
    media_type = cb.data.split(":")[-1].strip().lower()

    if media_type not in ALLOWED_MEDIA_TYPES:
        await cb.answer("Неизвестный тип", show_alert=True)
        return

    await state.update_data(media_type=media_type)
    await state.set_state(GetMediaStates.waiting_file_id)

    # можно убрать клавиатуру выбора типа
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await cb.answer()
    await cb.message.answer(
        f"Ок. Теперь пришлите file_id для типа <b>{media_type}</b>.",
        parse_mode=ParseMode.HTML,
        reply_markup=cancel_inline_kb(),
    )

@router.message(GetMediaStates.waiting_file_id)
async def getmedia_send(message: Message, state: FSMContext):
    file_id = (message.text or "").strip()
    if not file_id:
        await message.answer("Пришлите file_id текстом.", reply_markup=cancel_inline_kb())
        return

    data = await state.get_data()
    media_type = data.get("media_type")

    bot = message.bot
    chat_id = message.chat.id

    try:
        if media_type == "photo":
            await bot.send_photo(chat_id, photo=file_id, caption=f"<code>{file_id}</code>", parse_mode=ParseMode.HTML)
        elif media_type == "video":
            await bot.send_video(chat_id, video=file_id, caption=f"<code>{file_id}</code>", parse_mode=ParseMode.HTML)
        elif media_type == "audio":
            await bot.send_audio(chat_id, audio=file_id, caption=f"<code>{file_id}</code>", parse_mode=ParseMode.HTML)
        elif media_type == "voice":
            await bot.send_voice(chat_id, voice=file_id, caption=f"<code>{file_id}</code>", parse_mode=ParseMode.HTML)
        elif media_type == "document":
            await bot.send_document(chat_id, document=file_id, caption=f"<code>{file_id}</code>", parse_mode=ParseMode.HTML)
        elif media_type == "animation":
            await bot.send_animation(chat_id, animation=file_id, caption=f"<code>{file_id}</code>", parse_mode=ParseMode.HTML)
        elif media_type == "sticker":
            await bot.send_sticker(chat_id, sticker=file_id)
            await bot.send_message(chat_id, f"sticker file_id:\n<code>{file_id}</code>", parse_mode=ParseMode.HTML)
        elif media_type == "video_note":
            await bot.send_video_note(chat_id, video_note=file_id)
            await bot.send_message(chat_id, f"video_note file_id:\n<code>{file_id}</code>", parse_mode=ParseMode.HTML)
        else:
            await message.answer("Неизвестный тип. Начните заново: /getmedia")
            await state.clear()
            return

    except Exception:
        await message.answer("Не удалось отправить. Проверьте file_id (и доступ бота к файлу).", reply_markup=cancel_inline_kb())
        return

    await state.clear()
    await message.answer("Готово.")