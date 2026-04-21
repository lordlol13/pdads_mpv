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
        # PostgreSQL: deduplicate ai_news per-persona inside each raw_news group,
        # reassign remaining ai_news to the kept raw_news id, remove duplicate raw_news rows,
        # then create the unique index.
        op.execute("""
        DO $$
        DECLARE
            rec RECORD;
            keep_id INT;
            ids INT[];
        BEGIN
            FOR rec IN
                SELECT source_url, array_agg(id ORDER BY coalesce(created_at, to_timestamp(0)) DESC, id DESC) AS ids
                FROM raw_news
                WHERE source_url IS NOT NULL
                GROUP BY source_url
                HAVING COUNT(*) > 1
            LOOP
                ids := rec.ids;
                keep_id := ids[1];
                -- Reassign ai_news to the kept raw_news id
                UPDATE ai_news SET raw_news_id = keep_id WHERE raw_news_id = ANY(ids) AND raw_news_id <> keep_id;
                -- Delete duplicate raw_news rows (keep the chosen one)
                DELETE FROM raw_news WHERE id = ANY(ids) AND id <> keep_id;
            END LOOP;
        END$$;
        """)

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
