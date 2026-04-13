"""add oauth identities table

Revision ID: 20260413_0004
Revises: 20260407_0003
Create Date: 2026-04-13 12:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260413_0004"
down_revision = "20260407_0003"
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "oauth_identities"):
        op.create_table(
            "oauth_identities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=False),
            sa.Column("email", sa.Text(), nullable=True),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("avatar_url", sa.Text(), nullable=True),
            sa.Column("profile_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
            sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("provider", "subject", name="uq_oauth_identities_provider_subject"),
        )

    if _table_exists(bind, "oauth_identities") and not _index_exists(bind, "oauth_identities", "idx_oauth_identities_user_id"):
        op.create_index("idx_oauth_identities_user_id", "oauth_identities", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "oauth_identities") and _index_exists(bind, "oauth_identities", "idx_oauth_identities_user_id"):
        op.drop_index("idx_oauth_identities_user_id", table_name="oauth_identities")

    if _table_exists(bind, "oauth_identities"):
        op.drop_table("oauth_identities")
