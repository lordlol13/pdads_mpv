"""Add UNIQUE constraints and performance indexes.

Revision ID: 003
Revises: 20260424_0008
Create Date: 2026-05-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "20260424_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL: UNIQUE constraint for ai_news(raw_news_id, target_persona)
    # This prevents duplicate ai_news generation per raw_news + persona
    with op.batch_alter_table("ai_news", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_ai_news_raw_persona",
            ["raw_news_id", "target_persona"],
        )

    # Index for efficient raw_news batch queries
    op.create_index(
        "ix_raw_news_status_created",
        "raw_news",
        ["process_status", "created_at"],
    )

    # Index for user_feed queries (frequent JOINs and lookups)
    with op.batch_alter_table("user_feed", schema=None) as batch_op:
        batch_op.create_unique_constraint(
            "uq_user_feed_user_ai_news",
            ["user_id", "ai_news_id"],
        )

    # Index for efficient topic/persona filtering in users
    op.create_index(
        "ix_users_active",
        "users",
        ["is_active"],
    )


def downgrade() -> None:
    op.drop_index("ix_users_active", table_name="users")
    
    with op.batch_alter_table("user_feed", schema=None) as batch_op:
        batch_op.drop_constraint("uq_user_feed_user_ai_news", type_="unique")

    op.drop_index("ix_raw_news_status_created", table_name="raw_news")

    with op.batch_alter_table("ai_news", schema=None) as batch_op:
        batch_op.drop_constraint("uq_ai_news_raw_persona", type_="unique")
