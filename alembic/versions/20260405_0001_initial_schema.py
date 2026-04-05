"""initial schema

Revision ID: 20260405_0001
Revises: 
Create Date: 2026-04-05 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260405_0001"
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(bind, table_name: str) -> bool:
    return sa.inspect(bind).has_table(table_name)


def _index_exists(bind, table_name: str, index_name: str) -> bool:
    inspector = sa.inspect(bind)
    return any(index["name"] == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()

    if not _table_exists(bind, "users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(length=100), nullable=False),
            sa.Column("location", sa.String(length=255), nullable=True),
            sa.Column("interests", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
            sa.Column("email", sa.Text(), nullable=False),
            sa.Column("password_hash", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("TRUE"), nullable=True),
            sa.Column("is_verified", sa.Boolean(), server_default=sa.text("FALSE"), nullable=True),
            sa.Column("country_code", sa.String(length=8), nullable=True),
            sa.Column("region_code", sa.String(length=32), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )

    if not _table_exists(bind, "raw_news"):
        op.create_table(
            "raw_news",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("raw_text", sa.Text(), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("region", sa.String(length=100), nullable=True),
            sa.Column("is_urgent", sa.Boolean(), server_default=sa.text("FALSE"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
            sa.Column("process_status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=True),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.UniqueConstraint("content_hash", name="uq_raw_news_content_hash"),
        )

    if _table_exists(bind, "raw_news") and not _index_exists(bind, "raw_news", "idx_raw_news_status_created_at"):
        op.create_index("idx_raw_news_status_created_at", "raw_news", ["process_status", "created_at"], unique=False)

    if not _table_exists(bind, "ai_news"):
        op.create_table(
            "ai_news",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("raw_news_id", sa.Integer(), sa.ForeignKey("raw_news.id", ondelete="CASCADE"), nullable=False),
            sa.Column("target_persona", sa.String(length=100), nullable=False),
            sa.Column("final_title", sa.String(length=500), nullable=False),
            sa.Column("final_text", sa.Text(), nullable=False),
            sa.Column("image_urls", postgresql.ARRAY(sa.Text()), server_default=sa.text("ARRAY[]::TEXT[]"), nullable=True),
            sa.Column("category", sa.String(length=100), nullable=True),
            sa.Column("ai_score", sa.Numeric(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
            sa.Column("embedding_id", sa.String(length=255), nullable=True),
            sa.Column("vector_status", sa.String(length=32), server_default=sa.text("'pending'"), nullable=True),
            sa.UniqueConstraint("raw_news_id", "target_persona", name="uq_ai_news_raw_persona"),
        )

    if _table_exists(bind, "ai_news") and not _index_exists(bind, "ai_news", "idx_ai_news_created_at"):
        op.create_index("idx_ai_news_created_at", "ai_news", ["created_at"], unique=False)

    if not _table_exists(bind, "user_feed"):
        op.create_table(
            "user_feed",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ai_news_id", sa.Integer(), sa.ForeignKey("ai_news.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ai_score", sa.Numeric(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        )

    if _table_exists(bind, "user_feed") and not _index_exists(bind, "user_feed", "idx_user_feed_user_score"):
        op.create_index("idx_user_feed_user_score", "user_feed", ["user_id", "ai_score", "created_at"], unique=False)

    if not _table_exists(bind, "interactions"):
        op.create_table(
            "interactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ai_news_id", sa.Integer(), sa.ForeignKey("ai_news.id", ondelete="CASCADE"), nullable=False),
            sa.Column("liked", sa.Boolean(), nullable=True),
            sa.Column("viewed", sa.Boolean(), nullable=True),
            sa.Column("watch_time", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        )

    if _table_exists(bind, "interactions") and not _index_exists(bind, "interactions", "idx_interactions_user_news_created"):
        op.create_index("idx_interactions_user_news_created", "interactions", ["user_id", "ai_news_id", "created_at"], unique=False)

    if not _table_exists(bind, "feed_feature_log"):
        op.create_table(
            "feed_feature_log",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("ai_news_id", sa.Integer(), sa.ForeignKey("ai_news.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reason", sa.String(length=255), nullable=True),
            sa.Column("feature_value", sa.Numeric(), nullable=True),
            sa.Column("rank_position", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=True),
        )

    if _table_exists(bind, "feed_feature_log") and not _index_exists(bind, "feed_feature_log", "idx_feed_feature_log_user_created"):
        op.create_index("idx_feed_feature_log_user_created", "feed_feature_log", ["user_id", "created_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()

    if _table_exists(bind, "feed_feature_log") and _index_exists(bind, "feed_feature_log", "idx_feed_feature_log_user_created"):
        op.drop_index("idx_feed_feature_log_user_created", table_name="feed_feature_log")
    if _table_exists(bind, "feed_feature_log"):
        op.drop_table("feed_feature_log")

    if _table_exists(bind, "interactions") and _index_exists(bind, "interactions", "idx_interactions_user_news_created"):
        op.drop_index("idx_interactions_user_news_created", table_name="interactions")
    if _table_exists(bind, "interactions"):
        op.drop_table("interactions")

    if _table_exists(bind, "user_feed") and _index_exists(bind, "user_feed", "idx_user_feed_user_score"):
        op.drop_index("idx_user_feed_user_score", table_name="user_feed")
    if _table_exists(bind, "user_feed"):
        op.drop_table("user_feed")

    if _table_exists(bind, "ai_news") and _index_exists(bind, "ai_news", "idx_ai_news_created_at"):
        op.drop_index("idx_ai_news_created_at", table_name="ai_news")
    if _table_exists(bind, "ai_news"):
        op.drop_table("ai_news")

    if _table_exists(bind, "raw_news") and _index_exists(bind, "raw_news", "idx_raw_news_status_created_at"):
        op.drop_index("idx_raw_news_status_created_at", table_name="raw_news")
    if _table_exists(bind, "raw_news"):
        op.drop_table("raw_news")

    if _table_exists(bind, "users"):
        op.drop_table("users")
