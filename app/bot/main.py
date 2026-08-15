# app/bot/main.py

import asyncio
import logging
from contextlib import suppress
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Message, TelegramObject

from app.bot.routers import setup_routers
from app.config import BOT_TOKEN, DEBUG_LOG_INCOMING
from app.db.session import engine
from app.integrations.bitrix.client import BitrixClient
from app.logging_config import setup_logging
from app.services.auto_followup_service import worker_first_ping, worker_followup_after_first

logger = logging.getLogger(__name__)

_worker_tasks: list[asyncio.Task[Any]] = []

# Пауза перед перезапуском упавшего воркера.
_WORKER_RESTART_DELAY = 30


class DebugIncomingMiddleware(BaseMiddleware):
    """
    Пишет в лог каждое входящее сообщение целиком.
    Включается только через DEBUG_LOG_INCOMING=true: в логи попадает
    переписка клиентов, держать это включённым постоянно не стоит.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message):
            logger.debug(
                "INCOMING MESSAGE | chat_id=%s user_id=%s text=%r caption=%r",
                getattr(event.chat, "id", None),
                getattr(event.from_user, "id", None),
                event.text,
                event.caption,
            )
        return await handler(event, data)


# ===================== WORKERS =====================


async def _supervise(name: str, coro_factory: Callable[[], Awaitable[None]]) -> None:
    """
    Держит фоновый воркер живым: если он падает с необработанной ошибкой,
    логируем и перезапускаем, а не теряем молча до следующего рестарта бота.
    """
    while True:
        try:
            await coro_factory()
            logger.warning("Воркер %s завершился сам, перезапускаю", name)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Воркер %s упал, перезапуск через %s с", name, _WORKER_RESTART_DELAY)
        await asyncio.sleep(_WORKER_RESTART_DELAY)


# ===================== LIFECYCLE =====================


async def on_startup(bot: Bot):
    me = await bot.get_me()
    logger.info("Бот запущен. Логин: @%s, id=%s", me.username, me.id)

    workers: list[tuple[str, Callable[[], Awaitable[None]]]] = [
        ("worker_first_ping", lambda: worker_first_ping(bot)),
        ("worker_followup_after_first", lambda: worker_followup_after_first(bot)),
    ]

    _worker_tasks.clear()
    _worker_tasks.extend(
        asyncio.create_task(_supervise(name, factory), name=name) for name, factory in workers
    )


async def on_shutdown(bot: Bot):
    logger.info("Остановка: отменяю воркеры...")

    for task in _worker_tasks:
        task.cancel()

    for task in _worker_tasks:
        with suppress(asyncio.CancelledError):
            await task

    _worker_tasks.clear()

    await BitrixClient.close()
    await engine.dispose()

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

    if DEBUG_LOG_INCOMING:
        logger.warning("DEBUG_LOG_INCOMING включён: в логи попадёт текст переписки клиентов")
        dp.message.middleware(DebugIncomingMiddleware())

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    setup_routers(dp)

    logger.info("Запускаем polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
