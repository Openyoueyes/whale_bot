# app/bot/filters/admin.py

from __future__ import annotations

from typing import Union

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from app.config import ADMIN_IDS


class AdminFilter(BaseFilter):
    async def __call__(self, obj: Union[Message, CallbackQuery]) -> bool:
        user = getattr(obj, "from_user", None)
        if user is None:
            return False
        return user.id in ADMIN_IDS
