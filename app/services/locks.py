# app/services/locks.py
"""
Пер-клиентские локи.

Нужны там, где два параллельных апдейта одного пользователя могут создать
дубли в Bitrix (двойной /start, сообщение сразу после /start и т.п.).
Словарь чистится от свободных локов, чтобы не расти бесконечно.
"""

from __future__ import annotations

import asyncio

_LOCKS: dict[int, asyncio.Lock] = {}
_MAX_LOCKS = 2000


def _prune() -> None:
    """Выбрасываем локи, которые сейчас никто не держит."""
    for key in [k for k, lock in _LOCKS.items() if not lock.locked()]:
        _LOCKS.pop(key, None)


def client_lock(tg_id: int) -> asyncio.Lock:
    """
    Лок для конкретного клиента (создаётся при первом обращении).

    Вызывать только как `async with client_lock(tg_id):` — между получением
    объекта и захватом не должно быть await, иначе очистка может подменить лок.
    """
    lock = _LOCKS.get(tg_id)
    if lock is None:
        if len(_LOCKS) >= _MAX_LOCKS:
            _prune()
        lock = asyncio.Lock()
        _LOCKS[tg_id] = lock
    return lock
