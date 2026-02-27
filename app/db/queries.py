# app/db/queries.py
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CurrentManager


async def get_active_manager(session: AsyncSession) -> CurrentManager | None:
    res = await session.execute(
        select(CurrentManager).where(CurrentManager.is_active.is_(True)).limit(1)
    )
    return res.scalar_one_or_none()


async def list_managers(session: AsyncSession) -> list[CurrentManager]:
    res = await session.execute(select(CurrentManager).order_by(CurrentManager.id.asc()))
    return list(res.scalars().all())


async def set_active_manager(session: AsyncSession, manager_id: int) -> bool:
    """
    Делает одного менеджера активным.
    Возвращает True если менеджер найден.
    """
    # 1) всем false
    await session.execute(update(CurrentManager).values(is_active=False))

    # 2) выбранному true (через select -> чтобы понять, что он существует)
    obj = await session.get(CurrentManager, manager_id)
    if not obj:
        return False

    obj.is_active = True
    return True