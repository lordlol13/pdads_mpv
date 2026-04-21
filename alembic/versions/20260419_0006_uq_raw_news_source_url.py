"""add unique index on raw_news.source_url

Revision ID: 20260419_0006
Revises: 20260414_0005
Create Date: 2026-04-19 15:45:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260419_0006"
down_revision = "20260414_0005"
branch_labels = None
depends_on = None


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return False
    return any(idx.get("name") == index_name for idx in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("raw_news"):
        return

    if _index_exists(bind, "raw_news", "uq_raw_news_source_url"):
        return

    # Create unique index safely depending on dialect
    if bind.dialect.name == "sqlite":
        op.create_index("uq_raw_news_source_url", "raw_news", ["source_url"], unique=True)
    else:
        # PostgreSQL supports CREATE INDEX IF NOT EXISTS
        op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_news_source_url ON raw_news (source_url)")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("raw_news"):
        return

    if bind.dialect.name == "sqlite":
        try:
            op.drop_index("uq_raw_news_source_url", table_name="raw_news")
        except Exception:
            # best-effort
            pass
    else:
        op.execute("DROP INDEX IF EXISTS uq_raw_news_source_url")
