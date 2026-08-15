from __future__ import annotations

import asyncio
import logging
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# --- Логирование Alembic ---
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")

# --- Добавляем корень проекта в sys.path ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# --- Импорт приложения и моделей ---
from app.config import DATABASE_URL
from app.db.base import Base  # DeclarativeBase
from app.db.url import to_async_url, to_sync_url
from app.db import models  # noqa: F401  # чтобы модели повесились на Base.metadata

target_metadata = Base.metadata


def get_async_url() -> str:
    """Async-URL (asyncpg) — та же нормализация, что и в приложении."""
    return to_async_url(DATABASE_URL)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""

    # В оффлайне Alembic работает с sync-URL, драйвер не нужен.
    context.configure(
        url=to_sync_url(DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""

    async_url = get_async_url()

    connectable: AsyncEngine = create_async_engine(
        async_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # Важно: для Alembic используем sync connection
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online_sync() -> None:
    asyncio.run(run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online_sync()
