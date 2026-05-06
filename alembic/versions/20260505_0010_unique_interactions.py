"""Add unique interaction constraint.

Revision ID: 20260505_0010
Revises: 003
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op

revision = "20260505_0010"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        DELETE FROM interactions
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM interactions
            GROUP BY user_id, ai_news_id
        );
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_interactions_user_ai_news
        ON interactions (user_id, ai_news_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS uq_interactions_user_ai_news;
    """)
