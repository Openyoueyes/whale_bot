"""add auto_followup_state table

Revision ID: 9b1a2f3d4e01
Revises: b7f562417066
Create Date: 2026-02-01 12:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9b1a2f3d4e01"
down_revision = "b7f562417066"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auto_followup_state",
        sa.Column("tg_id", sa.BigInteger(), primary_key=True, nullable=False),

        sa.Column("deal_id", sa.String(length=32), nullable=True),

        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("last_activity_at", sa.DateTime(), nullable=True),

        sa.Column("first_sent_at", sa.DateTime(), nullable=True),
        sa.Column("second_sent_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("auto_followup_state")