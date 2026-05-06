"""Dialect-specific SQL fragments for raw text() queries."""

from sqlalchemy.ext.asyncio import AsyncSession


def sql_timestamp_now(session: AsyncSession) -> str:
    """SQLite has no NOW(); use CURRENT_TIMESTAMP for both when possible."""
    return "CURRENT_TIMESTAMP"
