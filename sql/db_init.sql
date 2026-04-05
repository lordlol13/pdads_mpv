-- LEGACY FILE
-- Schema initialization is managed exclusively by Alembic migrations.
-- Use this command from the project root:
--
--   alembic upgrade head
--
-- This file intentionally no longer creates tables to avoid schema drift.

DO $$
BEGIN
    RAISE NOTICE 'db_init.sql is deprecated. Use alembic upgrade head.';
END
$$;
