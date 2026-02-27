# app/db/session.py

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.engine import URL

from app.config import DATABASE_URL

# -------------------------------------------------------
# 1. Преобразуем sync-подключение psycopg2 → asyncpg
# -------------------------------------------------------
"""
Если в .env у тебя строка такого вида:

DATABASE_URL=postgresql+psycopg2://user:pass@localhost:5432/dbname

то SQLAlchemy не сможет использовать её как async.

Мы просто заменим драйвер psycopg2 → asyncpg.
"""
ASYNC_DATABASE_URL = DATABASE_URL.replace("psycopg2", "asyncpg")

# -------------------------------------------------------
# 2. Создаём async engine
# -------------------------------------------------------
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,  # можешь включить если нужно видеть SQL
    pool_pre_ping=True,
)

# -------------------------------------------------------
# 3. Создаём фабрику асинхронных сессий
# -------------------------------------------------------
async_session_maker = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)
