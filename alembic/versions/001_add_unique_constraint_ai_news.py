"""Add unique constraint on ai_news (raw_news_id, target_persona)

Revision ID: 001
Revises: 
Create Date: 2026-04-30 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add unique constraint to prevent duplicate ai_news entries."""
    # FIX START - Add unique constraint for absolute duplicate protection
    op.create_unique_constraint(
        'unique_raw_persona',
        'ai_news',
        ['raw_news_id', 'target_persona']
    )
    # FIX END


def downgrade() -> None:
    """Remove unique constraint."""
    op.drop_constraint('unique_raw_persona', 'ai_news', type_='unique')
