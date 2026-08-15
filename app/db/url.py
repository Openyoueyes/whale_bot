# app/db/url.py
"""
Нормализация строки подключения.

В .env URL обычно записан под синхронный драйвер (postgresql+psycopg2://...
или просто postgresql://...), а приложение целиком асинхронное и другого
драйвера, кроме asyncpg, в образе нет.

Вынесено отдельно от session.py, чтобы Alembic мог импортировать это,
не создавая engine приложения.
"""

from __future__ import annotations


def to_async_url(url: str) -> str:
    """Любой Postgres-URL → asyncpg."""
    if "+asyncpg" in url:
        return url

    scheme, sep, rest = url.partition("://")
    if not sep:
        return url

    base = scheme.split("+", 1)[0]
    if base in ("postgres", "postgresql"):
        return f"postgresql+asyncpg://{rest}"

    return url


def to_sync_url(url: str) -> str:
    """Тот же URL без указания драйвера — для offline-режима Alembic."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        return url
    return f"{scheme.split('+', 1)[0]}://{rest}"
