"""add processing_started_at to raw_news

Revision ID: 20260424_0008
Revises: 20260423_0008
Create Date: 2026-05-01 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "20260424_0008"
down_revision = "20260423_0008"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    now_func = "CURRENT_TIMESTAMP" if is_sqlite else "NOW()"

    if _table_exists(bind, "raw_news"):
        cols = {c["name"] for c in sa.inspect(bind).get_columns("raw_news")}
        if "processing_started_at" not in cols:
            op.add_column(
                "raw_news",
                sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
            )

        if not _index_exists(bind, "raw_news", "idx_raw_news_processing_started_at"):
            op.create_index(
                "idx_raw_news_processing_started_at",
                "raw_news",
                ["process_status", "processing_started_at"],
                unique=False,
            )

        # Preserve any already-running work by marking it as started now.
        op.execute(
            sa.text(
                f"""
                UPDATE raw_news
                SET processing_started_at = COALESCE(processing_started_at, {now_func})
                WHERE process_status = 'processing'
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "raw_news") and _index_exists(bind, "raw_news", "idx_raw_news_processing_started_at"):
        op.drop_index("idx_raw_news_processing_started_at", table_name="raw_news")

    if _table_exists(bind, "raw_news"):
        cols = {c["name"] for c in sa.inspect(bind).get_columns("raw_news")}
        if "processing_started_at" in cols:
            op.drop_column("raw_news", "processing_started_at")