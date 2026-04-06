"""Dialect-specific SQL fragments for raw text() queries."""

from sqlalchemy.ext.asyncio import AsyncSession


def sql_timestamp_now(session: AsyncSession) -> str:
    """SQLite has no NOW(); use CURRENT_TIMESTAMP for both when possible."""
    dialect = session.get_bind().dialect.name
    return "CURRENT_TIMESTAMP" if dialect == "sqlite" else "NOW()"
