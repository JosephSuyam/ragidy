-- Runs once, when the Postgres volume is first created. Schema changes belong in apps/api/alembic.
CREATE EXTENSION IF NOT EXISTS vector;
