"""add image_hash column to raw_news

Revision ID: 20260423_0007
Revises: 20260419_0006
Create Date: 2026-04-23 12:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260423_0007"
down_revision = "20260419_0006"
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

    # add nullable column if not exists
    if not inspector.has_table("raw_news"):
        return

    # safe add column for postgres/sqlite
    try:
        op.add_column("raw_news", sa.Column("image_hash", sa.Text(), nullable=True))
    except Exception:
        # best-effort: ignore if already present
        pass

    # Create unique index on image_hash for non-null values
    index_name = "idx_raw_news_image_hash"
    if _index_exists(bind, "raw_news", index_name):
        return

    if bind.dialect.name == "sqlite":
        # sqlite: create unique index allowing multiple NULLs
        try:
            op.create_index(index_name, "raw_news", ["image_hash"], unique=True)
        except Exception:
            pass
    else:
        # PostgreSQL: create a partial unique index for non-null image_hash
        op.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON raw_news (image_hash) WHERE image_hash IS NOT NULL")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("raw_news"):
        return

    index_name = "idx_raw_news_image_hash"
    if bind.dialect.name == "sqlite":
        try:
            op.drop_index(index_name, table_name="raw_news")
        except Exception:
            pass
    else:
        op.execute(f"DROP INDEX IF EXISTS {index_name}")

    # drop column if exists
    try:
        op.drop_column("raw_news", "image_hash")
    except Exception:
        pass
