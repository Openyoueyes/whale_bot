"""init user and referral tags

Revision ID: 0001_init_user_tags
Revises:
Create Date: 2025-12-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_init_user_tags"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Таблица tg_user ---
    op.create_table(
        "tg_user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("tg_username", sa.String(length=255), nullable=True),
        sa.Column("tg_firstname", sa.String(length=255), nullable=True),
        sa.Column("tg_lastname", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        op.f("ix_tg_user_id"),
        "tg_user",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tg_user_tg_id"),
        "tg_user",
        ["tg_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_tg_user_tg_username"),
        "tg_user",
        ["tg_username"],
        unique=False,
    )

    # --- Таблица referral_tag ---
    op.create_table(
        "referral_tag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tag", sa.String(length=64), nullable=False),
        sa.Column(
            "clicks",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        op.f("ix_referral_tag_tag"),
        "referral_tag",
        ["tag"],
        unique=True,
    )

    # --- Таблица tg_user_tag ---
    op.create_table(
        "tg_user_tag",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tg_user_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["tg_user_id"],
            ["tg_user.id"],
            name="fk_tg_user_tag_tg_user_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"],
            ["referral_tag.id"],
            name="fk_tg_user_tag_referral_tag_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tg_user_id",
            "tag_id",
            name="_user_tag_uc",
        ),
    )


def downgrade() -> None:
    op.drop_table("tg_user_tag")
    op.drop_index(op.f("ix_referral_tag_tag"), table_name="referral_tag")
    op.drop_table("referral_tag")
    op.drop_index(op.f("ix_tg_user_tg_username"), table_name="tg_user")
    op.drop_index(op.f("ix_tg_user_tg_id"), table_name="tg_user")
    op.drop_index(op.f("ix_tg_user_id"), table_name="tg_user")
    op.drop_table("tg_user")
