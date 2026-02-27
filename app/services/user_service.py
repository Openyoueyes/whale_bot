# app/services/user_service.py

from typing import Optional

from aiogram.types import User as TgUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TGUser, ReferralTag, TGUserTag

DEFAULT_REFERRAL_TAG = "not_tag"


async def get_or_create_tg_user(
        session: AsyncSession,
        tg_user: TgUser,
) -> TGUser:
    result = await session.execute(
        select(TGUser).where(TGUser.tg_id == tg_user.id)
    )
    user: Optional[TGUser] = result.scalar_one_or_none()

    if user is None:
        user = TGUser(
            tg_id=tg_user.id,
            tg_username=tg_user.username,
            tg_firstname=tg_user.first_name,
            tg_lastname=tg_user.last_name,
        )
        session.add(user)
        await session.flush()

    return user


async def process_referral_tag_for_user(
        session: AsyncSession,
        user: TGUser,
        raw_tag: str | None,
) -> tuple[str, bool]:
    """
    Обрабатываем тег из /start.

    Возвращаем:
      - tag_value: фактический тег (включая 'not_tag', если ничего не было)
      - is_first_visit: True, если пользователь впервые пришёл с этим тегом
    """

    # 0. Нормализуем тег, подставляем not_tag при отсутствии
    if raw_tag is None:
        tag_value = DEFAULT_REFERRAL_TAG
    else:
        raw_tag = raw_tag.strip()
        tag_value = raw_tag or DEFAULT_REFERRAL_TAG

    # 1. Ищем/создаём ReferralTag
    result = await session.execute(
        select(ReferralTag).where(ReferralTag.tag == tag_value)
    )
    tag = result.scalar_one_or_none()

    if tag is None:
        tag = ReferralTag(tag=tag_value, clicks=0)
        session.add(tag)
        await session.flush()

    # 2. Проверяем, есть ли уже связка user-tag
    result = await session.execute(
        select(TGUserTag).where(
            TGUserTag.tg_user_id == user.id,
            TGUserTag.tag_id == tag.id,
        )
    )
    user_tag = result.scalar_one_or_none()

    is_first_visit = False

    if user_tag is None:
        # первый раз видим этого юзера с таким тегом
        user_tag = TGUserTag(
            tg_user_id=user.id,
            tag_id=tag.id,
        )
        session.add(user_tag)

        tag.clicks += 1
        is_first_visit = True

    # commit делаем снаружи
    return tag_value, is_first_visit
