import os

import asyncpg

DATABASE_URL = os.getenv("DATABASE_URL")

_pool: asyncpg.Pool | None = None


async def connect_database() -> None:
    global _pool
    if not DATABASE_URL:
        return
    _pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5)
    await init_database()


async def close_database() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if not _pool:
        raise RuntimeError("Database pool is not initialized")
    return _pool


async def init_database() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                id BIGSERIAL PRIMARY KEY,
                experiment_key TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                primary_metric TEXT NOT NULL,
                guardrail_metric TEXT,
                status TEXT NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'running', 'paused', 'completed')),
                allocation JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_by TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                started_at TIMESTAMPTZ,
                ended_at TIMESTAMPTZ
            );

            CREATE TABLE IF NOT EXISTS experiment_variants (
                id BIGSERIAL PRIMARY KEY,
                experiment_id BIGINT NOT NULL REFERENCES experiments(id)
                    ON DELETE CASCADE,
                variant_key TEXT NOT NULL,
                label TEXT NOT NULL,
                config JSONB NOT NULL DEFAULT '{}'::jsonb,
                weight INT NOT NULL DEFAULT 50 CHECK (weight >= 0),
                UNIQUE (experiment_id, variant_key)
            );

            CREATE TABLE IF NOT EXISTS experiment_assignments (
                experiment_id BIGINT NOT NULL REFERENCES experiments(id)
                    ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                variant_key TEXT NOT NULL,
                assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (experiment_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS experiment_events (
                id BIGSERIAL PRIMARY KEY,
                experiment_id BIGINT REFERENCES experiments(id)
                    ON DELETE SET NULL,
                experiment_key TEXT NOT NULL,
                user_id TEXT NOT NULL,
                variant_key TEXT,
                event_name TEXT NOT NULL,
                properties JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_experiment_events_lookup
                ON experiment_events(experiment_key, event_name, variant_key);
            CREATE INDEX IF NOT EXISTS idx_experiment_assignments_lookup
                ON experiment_assignments(experiment_id, variant_key);
            """
        )
