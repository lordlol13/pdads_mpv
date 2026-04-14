"""add embedding_vector columns to ai_news and users

Revision ID: 20260414_0005
Revises: 20260413_0004
Create Date: 2026-04-14 14:30:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260414_0005"
down_revision = "20260413_0004"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table(table_name):
        return set()
    return {c["name"] for c in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    ai_cols = _column_names(bind, "ai_news")
    user_cols = _column_names(bind, "users")

    # ai_news: embedding vector, model, updated timestamp
    if "embedding_vector" not in ai_cols:
        if is_sqlite:
            op.add_column(
                "ai_news",
                sa.Column("embedding_vector", sa.Text(), server_default=sa.text("'[]'"), nullable=True),
            )
        else:
            op.execute(
                """
                ALTER TABLE IF EXISTS ai_news
                ADD COLUMN IF NOT EXISTS embedding_vector JSONB
                """
            )

    if "embedding_model" not in ai_cols:
        if is_sqlite:
            op.add_column("ai_news", sa.Column("embedding_model", sa.Text(), nullable=True))
        else:
            op.execute(
                """
                ALTER TABLE IF EXISTS ai_news
                ADD COLUMN IF NOT EXISTS embedding_model TEXT
                """
            )

    if "embedding_updated_at" not in ai_cols:
        if is_sqlite:
            op.add_column("ai_news", sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True))
        else:
            op.execute(
                """
                ALTER TABLE IF EXISTS ai_news
                ADD COLUMN IF NOT EXISTS embedding_updated_at TIMESTAMPTZ
                """
            )

    # users: embedding vector, model, updated timestamp
    if "embedding_vector" not in user_cols:
        if is_sqlite:
            op.add_column(
                "users",
                sa.Column("embedding_vector", sa.Text(), server_default=sa.text("'[]'"), nullable=True),
            )
        else:
            op.execute(
                """
                ALTER TABLE IF EXISTS users
                ADD COLUMN IF NOT EXISTS embedding_vector JSONB
                """
            )

    if "embedding_model" not in user_cols:
        if is_sqlite:
            op.add_column("users", sa.Column("embedding_model", sa.Text(), nullable=True))
        else:
            op.execute(
                """
                ALTER TABLE IF EXISTS users
                ADD COLUMN IF NOT EXISTS embedding_model TEXT
                """
            )

    if "embedding_updated_at" not in user_cols:
        if is_sqlite:
            op.add_column("users", sa.Column("embedding_updated_at", sa.DateTime(timezone=True), nullable=True))
        else:
            op.execute(
                """
                ALTER TABLE IF EXISTS users
                ADD COLUMN IF NOT EXISTS embedding_updated_at TIMESTAMPTZ
                """
            )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    ai_cols = _column_names(bind, "ai_news")
    user_cols = _column_names(bind, "users")

    # ai_news: drop in reverse order
    if "embedding_updated_at" in ai_cols:
        if is_sqlite:
            with op.batch_alter_table("ai_news") as batch:
                batch.drop_column("embedding_updated_at")
        else:
            op.execute("ALTER TABLE IF EXISTS ai_news DROP COLUMN IF EXISTS embedding_updated_at")

    if "embedding_model" in ai_cols:
        if is_sqlite:
            with op.batch_alter_table("ai_news") as batch:
                batch.drop_column("embedding_model")
        else:
            op.execute("ALTER TABLE IF EXISTS ai_news DROP COLUMN IF EXISTS embedding_model")

    if "embedding_vector" in ai_cols:
        if is_sqlite:
            with op.batch_alter_table("ai_news") as batch:
                batch.drop_column("embedding_vector")
        else:
            op.execute("ALTER TABLE IF EXISTS ai_news DROP COLUMN IF EXISTS embedding_vector")

    # users: drop in reverse order
    if "embedding_updated_at" in user_cols:
        if is_sqlite:
            with op.batch_alter_table("users") as batch:
                batch.drop_column("embedding_updated_at")
        else:
            op.execute("ALTER TABLE IF EXISTS users DROP COLUMN IF EXISTS embedding_updated_at")

    if "embedding_model" in user_cols:
        if is_sqlite:
            with op.batch_alter_table("users") as batch:
                batch.drop_column("embedding_model")
        else:
            op.execute("ALTER TABLE IF EXISTS users DROP COLUMN IF EXISTS embedding_model")

    if "embedding_vector" in user_cols:
        if is_sqlite:
            with op.batch_alter_table("users") as batch:
                batch.drop_column("embedding_vector")
        else:
            op.execute("ALTER TABLE IF EXISTS users DROP COLUMN IF EXISTS embedding_vector")
