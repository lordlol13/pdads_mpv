"""add image_url to raw_news

Revision ID: 20260407_0003
Revises: 20260405_0002
Create Date: 2026-04-07 03:45:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260407_0003"
down_revision = "20260405_0002"
branch_labels = None
depends_on = None


def _raw_news_column_names(bind) -> set[str]:
    inspector = sa.inspect(bind)
    if not inspector.has_table("raw_news"):
        return set()
    return {c["name"] for c in inspector.get_columns("raw_news")}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _raw_news_column_names(bind)
    if "image_url" in cols:
        return

    op.add_column("raw_news", sa.Column("image_url", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = _raw_news_column_names(bind)
    if "image_url" not in cols:
        return

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("raw_news") as batch:
            batch.drop_column("image_url")
    else:
        op.drop_column("raw_news", "image_url")
