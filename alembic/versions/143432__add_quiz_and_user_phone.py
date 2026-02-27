"""add quiz tables + phone/quiz flags

Revision ID: XXXX_add_quiz_and_user_phone
Revises: 9b1a2f3d4e01
Create Date: 2026-02-11 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "143432__add_quiz_and_user_phone"
down_revision = "9b1a2f3d4e01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- tg_user: phone + quiz flags
    op.add_column("tg_user", sa.Column("tg_phone", sa.String(length=32), nullable=True))
    op.add_column("tg_user", sa.Column("quiz_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("tg_user", sa.Column("quiz_completed_at", sa.DateTime(), nullable=True))

    # --- quiz_session
    op.create_table(
        "quiz_session",
        sa.Column("tg_id", sa.BigInteger(), sa.ForeignKey("tg_user.tg_id", ondelete="CASCADE"), primary_key=True, nullable=False),
        sa.Column("step", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("gift", sa.String(length=32), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # --- quiz_answer
    op.create_table(
        "quiz_answer",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tg_id", sa.BigInteger(), sa.ForeignKey("tg_user.tg_id", ondelete="CASCADE"), nullable=False),
        sa.Column("q_key", sa.String(length=64), nullable=False),
        sa.Column("answer", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_quiz_answer_tg_id", "quiz_answer", ["tg_id"], unique=False)
    op.create_index("ix_quiz_answer_q_key", "quiz_answer", ["q_key"], unique=False)

    # server_default убираем (чтобы модель была источником правды)
    op.alter_column("tg_user", "quiz_completed", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_quiz_answer_q_key", table_name="quiz_answer")
    op.drop_index("ix_quiz_answer_tg_id", table_name="quiz_answer")
    op.drop_table("quiz_answer")
    op.drop_table("quiz_session")

    op.drop_column("tg_user", "quiz_completed_at")
    op.drop_column("tg_user", "quiz_completed")
    op.drop_column("tg_user", "tg_phone")