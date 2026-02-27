# app/logging_config.py

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_LEVEL = logging.INFO


def setup_logging() -> None:
    """Базовая настройка логирования для бота."""
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)

    log_format = "[%(asctime)s] [%(levelname)s] %(name)s: %(message)s"

    handlers = [
        logging.StreamHandler(),  # вывод в консоль
        RotatingFileHandler(
            logs_dir / "bot.log",
            maxBytes=5_000_000,
            backupCount=3,
            encoding="utf-8",
        ),
    ]

    logging.basicConfig(
        level=LOG_LEVEL,
        format=log_format,
        handlers=handlers,
    )
