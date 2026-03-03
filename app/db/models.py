# app/db/models.py

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    String,
    Integer,
    DateTime,
    ForeignKey,
    UniqueConstraint, BigInteger, Text, Boolean
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
    relationship,
)

from typing import Any, Dict

from sqlalchemy.dialects.postgresql import JSONB

from app.db.base import Base  # см. ниже Base


class TGUser(Base):
    __tablename__ = "tg_user"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    tg_username: Mapped[str | None] = mapped_column(String(255), index=True)
    tg_firstname: Mapped[str | None] = mapped_column(String(255))
    tg_lastname: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # ✅ новое
    tg_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quiz_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    quiz_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # связи с тегами
    tags: Mapped[list["TGUserTag"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )

    # ✅ one-to-one на сессию теста
    quiz_session: Mapped["QuizSession | None"] = relationship(
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ReferralTag(Base):
    __tablename__ = "referral_tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    tag: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # лимит Telegram
    clicks: Mapped[int] = mapped_column(Integer, default=0)  # уникальные юзеры

    users: Mapped[list["TGUserTag"]] = relationship(
        back_populates="tag",
        cascade="all, delete-orphan",
    )


class TGUserTag(Base):
    """
    Связка «пользователь-метка».
    Нужна, чтобы понять, показывали ли мы уже этот tag данному пользователю.
    """
    __tablename__ = "tg_user_tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(ForeignKey("tg_user.id"))
    tag_id: Mapped[int] = mapped_column(ForeignKey("referral_tag.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
    )

    __table_args__ = (
        UniqueConstraint("tg_user_id", "tag_id", name="_user_tag_uc"),
    )

    user: Mapped["TGUser"] = relationship(back_populates="tags")
    tag: Mapped["ReferralTag"] = relationship(back_populates="users")


class TriggerReply(Base):
    __tablename__ = "trigger_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # ключевое слово/фраза (в нижнем регистре, без пробелов по краям)
    keyword: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)

    # любой текст-описание для админа (опционально)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # включен/выключен
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # тип контента: text/photo/video/document/voice/audio/sticker
    content_type: Mapped[str] = mapped_column(String(32), nullable=False)

    # текст/капшен (HTML допускается)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # payload для медиа (file_id, file_name и т.п.)
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class AutoFollowupState(Base):
    __tablename__ = "auto_followup_state"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    # на всякий — чтобы не искать лишний раз
    deal_id: Mapped[str | None] = mapped_column(String(32), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    first_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    second_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class QuizSession(Base):
    __tablename__ = "quiz_session"

    tg_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tg_user.tg_id", ondelete="CASCADE"),
        primary_key=True,
    )

    step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    finished: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    gift: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    level: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    user: Mapped["TGUser"] = relationship(back_populates="quiz_session")


class QuizAnswer(Base):
    __tablename__ = "quiz_answer"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    tg_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("tg_user.tg_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    q_key: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    answer: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)


class CurrentManager(Base):
    __tablename__ = "current_manager"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    tg_link: Mapped[str] = mapped_column(String(255), nullable=False)  # https://t.me/... или @...
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
