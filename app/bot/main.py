# app/bot/main.py

import asyncio
import logging
from contextlib import suppress
from typing import Any

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message

from app.config import BOT_TOKEN
from app.bot.routers import setup_routers
from app.logging_config import setup_logging
from app.services.auto_followup_service import worker_autoping_1, worker_autoping_2, worker_autolose

# ✅ воркеры (подставь свой реальный путь/имена функций)


logger = logging.getLogger(__name__)

_worker_tasks: list[asyncio.Task[Any]] = []


# ===================== DEBUG MIDDLEWARE =====================

class DebugIncomingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, Message):
            logger.warning(
                "INCOMING MESSAGE | chat_id=%s user_id=%s text=%r caption=%r entities=%r",
                getattr(event.chat, "id", None),
                getattr(event.from_user, "id", None),
                event.text,
                event.caption,
                event.entities,
            )
        return await handler(event, data)


# ===================== LIFECYCLE =====================

async def on_startup(bot: Bot):
    me = await bot.get_me()
    logger.info("Бот запущен. Логин: @%s, id=%s", me.username, me.id)

    # ✅ запускаем воркеры (бесконечные циклы) как фоновые задачи
    _worker_tasks.clear()
    _worker_tasks.extend(
        [
            asyncio.create_task(worker_autoping_1(bot), name="worker_autoping_1"),
            asyncio.create_task(worker_autoping_2(bot), name="worker_autoping_2"),
            asyncio.create_task(worker_autolose(bot), name="worker_autolose"),
        ]
    )


async def on_shutdown(bot: Bot):
    logger.info("Остановка: отменяю воркеры...")

    for t in _worker_tasks:
        t.cancel()

    for t in _worker_tasks:
        with suppress(asyncio.CancelledError):
            await t

    logger.info("Бот остановлен.")


# ===================== MAIN =====================

async def main():
    setup_logging()
    logger.info("Инициализация бота...")

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    # 🔥 ВАЖНО: middleware ДО роутеров
    dp.message.middleware(DebugIncomingMiddleware())

    # хуки старта/остановки
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    setup_routers(dp)

    logger.info("Запускаем polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())