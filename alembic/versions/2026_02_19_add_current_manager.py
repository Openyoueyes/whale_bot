"""add current_manager table

Revision ID: 2026_02_19_add_current_manager
Revises: 143432__add_quiz_and_user_phone
Create Date: 2026-02-19 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "2026_02_19_add_current_manager"
down_revision = "143432__add_quiz_and_user_phone"
branch_labels = None
depends_on = None


IDX_ONE_ACTIVE = "uq_current_manager_one_active_true"
UQ_NAME = "uq_current_manager_name"


def upgrade() -> None:
    op.create_table(
        "current_manager",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("tg_link", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
    )

    # уникальное имя менеджера
    op.create_unique_constraint(UQ_NAME, "current_manager", ["name"])

    # Postgres: только один is_active=true (partial unique index)
    # Важно: это именно индекс, constraint так не сделать корректно.
    op.create_index(
        IDX_ONE_ACTIVE,
        "current_manager",
        ["is_active"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )

    # server_default убираем, чтобы модель была источником правды
    op.alter_column("current_manager", "is_active", server_default=None)


def downgrade() -> None:
    # индекс
    op.drop_index(IDX_ONE_ACTIVE, table_name="current_manager")

    # unique constraint
    op.drop_constraint(UQ_NAME, "current_manager", type_="unique")

    op.drop_table("current_manager")