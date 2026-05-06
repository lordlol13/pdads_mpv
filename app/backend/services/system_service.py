from __future__ import annotations
from typing import Optional
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def ensure_system_state_table(session: AsyncSession) -> None:
    """Ensure `system_state` table exists. Safe to call repeatedly."""
    try:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS system_state (
                    name TEXT PRIMARY KEY,
                    last_parsed_at TIMESTAMP WITH TIME ZONE
                )
                """
            )
        )
        await session.commit()
    except Exception as e:
        logger.exception(f"ensure_system_state_table failed: {e}")
        try:
            await session.rollback()
        except Exception:
            pass


async def update_last_parsed_at(session: AsyncSession, name: str = "parser") -> None:
    """Upsert last_parsed_at for the given name.

    Uses `now()` on the DB server to avoid timezone drift between hosts.
    """
    try:
        await ensure_system_state_table(session)
        await session.execute(
            text(
                """
                INSERT INTO system_state (name, last_parsed_at)
                VALUES (:name, now())
                ON CONFLICT (name) DO UPDATE SET last_parsed_at = EXCLUDED.last_parsed_at
                """
            ),
            {"name": name},
        )
        await session.commit()
    except Exception as e:
        logger.exception(f"update_last_parsed_at failed: {e}")
        try:
            await session.rollback()
        except Exception:
            pass
