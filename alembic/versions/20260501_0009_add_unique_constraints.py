"""Add UNIQUE constraints and performance indexes (IDEMPOTENT).

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
    # IDEMPOTENT: Safe to run multiple times
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_ai_news_raw_persona'
            ) THEN
                ALTER TABLE ai_news
                ADD CONSTRAINT uq_ai_news_raw_persona
                UNIQUE (raw_news_id, target_persona);
            END IF;
        END
        $$;
    """)

    # Index for efficient raw_news batch queries (IDEMPOTENT)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_raw_news_status_created
        ON raw_news (process_status, created_at);
    """)

    # UNIQUE constraint for user_feed(user_id, ai_news_id) - IDEMPOTENT
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_user_feed_user_ai_news'
            ) THEN
                ALTER TABLE user_feed
                ADD CONSTRAINT uq_user_feed_user_ai_news
                UNIQUE (user_id, ai_news_id);
            END IF;
        END
        $$;
    """)

    # Index for efficient filtering on users.is_active - IDEMPOTENT
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_users_active
        ON users (is_active);
    """)


def downgrade() -> None:
    # IDEMPOTENT: Use IF EXISTS for safe rollback
    op.execute("""
        DROP INDEX IF EXISTS ix_users_active;
    """)

    op.execute("""
        ALTER TABLE user_feed
        DROP CONSTRAINT IF EXISTS uq_user_feed_user_ai_news;
    """)

    op.execute("""
        DROP INDEX IF EXISTS ix_raw_news_status_created;
    """)

    op.execute("""
        ALTER TABLE ai_news
        DROP CONSTRAINT IF EXISTS uq_ai_news_raw_persona;
    """)
