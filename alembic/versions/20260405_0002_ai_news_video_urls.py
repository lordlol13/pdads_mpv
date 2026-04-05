"""add video_urls to ai_news

Revision ID: 20260405_0002
Revises: 20260405_0001
Create Date: 2026-04-05 00:30:00
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260405_0002"
down_revision = "20260405_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE IF EXISTS ai_news
        ADD COLUMN IF NOT EXISTS video_urls TEXT[] DEFAULT ARRAY[]::TEXT[]
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE IF EXISTS ai_news
        DROP COLUMN IF EXISTS video_urls
        """
    )
