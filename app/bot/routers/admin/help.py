# app/bot/routers/admin/help.py

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.bot.filters.admin import AdminFilter

router = Router(name="admin-help")
router.message.filter(AdminFilter())


@router.message(Command("admin"))
async def cmd_admin_help(message: Message):
    text = (
        "🛠 <b>Админ-панель Whale Trade</b>\n\n"

        "Ниже список доступных команд и что они делают.\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>1) Диалог с клиентами</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• <code>/send_to</code>\n"
        "  Отправка сообщения клиенту по TG ID.\n"
        "  Поддерживает <b>все типы</b>: текст, фото+caption, видео+caption, voice, audio, document, кружки, стикеры и т.д.\n"
        "  <i>Как работает:</i> бот спросит TG ID → затем вы отправляете сообщение.\n\n"
        "• Кнопка «Ответить клиенту» (в админ-карточке)\n"
        "  Быстрый ответ клиенту прямо из уведомления.\n"
        "  Поддерживает <b>все типы</b> сообщений.\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>2) Рассылки</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• <code>/broadcast</code>\n"
        "  Рассылка по клиентам из Bitrix.\n"
        "  Режимы:\n"
        "  - все воронки/стадии\n"
        "  - по воронке\n"
        "  - по стадии\n"
        "  Затем вы отправляете сообщение (любой тип) → бот делает копию каждому получателю.\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>3) Триггеры авто-ответов</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• <code>/triggers</code>\n"
        "  Меню управления триггерами.\n"
        "  Триггер: клиент пишет ключевое слово → бот отвечает сохранённым сообщением.\n\n"
        "• <code>/trigger_on keyword</code> — включить триггер\n"
        "• <code>/trigger_off keyword</code> — выключить триггер\n"
        "• <code>/trigger_del keyword</code> — удалить триггер\n\n"

        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>4) Получение медиа по file_id</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• <code>/getmedia</code>\n"
        "  Отправляет вам медиа по известному <code>file_id</code>.\n"
        "  Как работает: выбрать тип → вставить file_id → бот вернёт файл.\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>5) Смена менеджера</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• /change_manager\n"
        "  Выбираем активного манагера в кнопках.\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>6) Отмена FSM</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• Inline-кнопка <b>«❌ Отмена»</b> в сценариях\n"
        "  Сбрасывает текущее состояние (FSM) и прекращает действие.\n\n"
    )

    await message.answer(text, parse_mode="HTML")