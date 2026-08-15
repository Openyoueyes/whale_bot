# app/logging_config.py

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_LEVEL = logging.INFO
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"


def _file_handler() -> logging.Handler | None:
    """
    Файловый лог — вещь желательная, но не обязательная.
    Если каталог примонтирован с чужими правами (частый случай с bind-mount
    и не-root пользователем в контейнере), бот не должен падать при старте.
    """
    try:
        logs_dir = Path("logs")
        logs_dir.mkdir(exist_ok=True)
        return RotatingFileHandler(
            logs_dir / "bot.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        return None


def setup_logging() -> None:
    """Базовая настройка логирования для бота."""
    handlers: list[logging.Handler] = [logging.StreamHandler()]

    file_handler = _file_handler()
    if file_handler is not None:
        handlers.append(file_handler)

    logging.basicConfig(level=LOG_LEVEL, format=LOG_FORMAT, handlers=handlers)

    if file_handler is None:
        logging.getLogger(__name__).warning(
            "Не удалось открыть logs/bot.log — пишу только в stdout. "
            "Проверьте права на каталог logs."
        )
