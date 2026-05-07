"""Add feed_comments and saved_news tables

Revision ID: a5cce99e9e24
Revises: 20260505_0010
Create Date: 2026-05-07 12:37:47.274794
"""

from alembic import op
import sqlalchemy as sa



# revision identifiers, used by Alembic.
revision = 'a5cce99e9e24'
down_revision = '20260505_0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create feed_comments table
    op.create_table(
        'feed_comments',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('ai_news_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('parent_comment_id', sa.BigInteger(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ai_news_id'], ['ai_news.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['parent_comment_id'], ['feed_comments.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_feed_comments_ai_news_created', 'feed_comments', ['ai_news_id', 'created_at'])
    op.create_index('idx_feed_comments_parent', 'feed_comments', ['parent_comment_id'])
    
    # Create saved_news table
    op.create_table(
        'saved_news',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('ai_news_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['ai_news_id'], ['ai_news.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'ai_news_id', name='uq_saved_news_user_ai_news')
    )
    op.create_index('idx_saved_news_user', 'saved_news', ['user_id'])
    op.create_index('idx_saved_news_ai_news', 'saved_news', ['ai_news_id'])


def downgrade() -> None:
    op.drop_index('idx_saved_news_ai_news', table_name='saved_news')
    op.drop_index('idx_saved_news_user', table_name='saved_news')
    op.drop_table('saved_news')
    op.drop_index('idx_feed_comments_parent', table_name='feed_comments')
    op.drop_index('idx_feed_comments_ai_news_created', table_name='feed_comments')
    op.drop_table('feed_comments')
