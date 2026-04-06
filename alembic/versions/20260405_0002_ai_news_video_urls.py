"""add video_urls to ai_news

Revision ID: 20260405_0002
Revises: 20260405_0001
Create Date: 2026-04-05 00:30:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260405_0002"
down_revision = "20260405_0001"
branch_labels = None
depends_on = None


def _ai_news_column_names(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table("ai_news"):
        return set()
    return {c["name"] for c in inspector.get_columns("ai_news")}


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    cols = _ai_news_column_names(bind)
    if "video_urls" in cols:
        return
    if is_sqlite:
        op.add_column(
            "ai_news",
            sa.Column("video_urls", sa.Text(), server_default=sa.text("'[]'"), nullable=True),
        )
    else:
        op.execute(
            """
            ALTER TABLE IF EXISTS ai_news
            ADD COLUMN IF NOT EXISTS video_urls TEXT[] DEFAULT ARRAY[]::TEXT[]
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    cols = _ai_news_column_names(bind)
    if "video_urls" not in cols:
        return
    if is_sqlite:
        with op.batch_alter_table("ai_news") as batch:
            batch.drop_column("video_urls")
    else:
        op.execute(
            """
            ALTER TABLE IF EXISTS ai_news
            DROP COLUMN IF EXISTS video_urls
            """
        )
