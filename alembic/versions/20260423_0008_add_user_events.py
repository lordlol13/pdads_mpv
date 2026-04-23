"""create user_events table

Revision ID: 20260423_0008
Revises: 20260423_0007
Create Date: 2026-04-23 12:10:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260423_0008"
down_revision = "20260423_0007"
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
    if inspector.has_table("user_events"):
        return

    now_func = "CURRENT_TIMESTAMP" if bind.dialect.name == "sqlite" else "NOW()"

    # Create table
    op.create_table(
        "user_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("dwell_time", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text(now_func), nullable=True),
    )

    # Add composite index for efficient user timeline queries
    index_name = "idx_user_events_user_created"
    if not _index_exists(bind, "user_events", index_name):
        try:
            op.create_index(index_name, "user_events", ["user_id", "created_at"], unique=False)
        except Exception:
            # best-effort: ignore if index creation fails on some dialects
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("user_events"):
        return

    index_name = "idx_user_events_user_created"
    try:
        if bind.dialect.name == "sqlite":
            op.drop_index(index_name, table_name="user_events")
        else:
            op.execute(f"DROP INDEX IF EXISTS {index_name}")
    except Exception:
        pass

    try:
        op.drop_table("user_events")
    except Exception:
        pass
