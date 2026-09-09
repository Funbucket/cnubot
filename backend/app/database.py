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
                unit TEXT NOT NULL DEFAULT 'user',
                alpha DOUBLE PRECISION NOT NULL DEFAULT 0.05,
                power DOUBLE PRECISION NOT NULL DEFAULT 0.8,
                baseline_rate DOUBLE PRECISION,
                mde DOUBLE PRECISION,
                min_sample_size INT,
                analysis_plan JSONB NOT NULL DEFAULT '{}'::jsonb,
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
                first_exposed_at TIMESTAMPTZ,
                PRIMARY KEY (experiment_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS experiment_events (
                id BIGSERIAL PRIMARY KEY,
                event_id TEXT,
                experiment_id BIGINT REFERENCES experiments(id)
                    ON DELETE SET NULL,
                experiment_key TEXT NOT NULL,
                user_id TEXT NOT NULL,
                variant_key TEXT,
                event_name TEXT NOT NULL,
                properties JSONB NOT NULL DEFAULT '{}'::jsonb,
                source TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS experiment_daily_rollups (
                experiment_id BIGINT NOT NULL REFERENCES experiments(id)
                    ON DELETE CASCADE,
                rollup_date DATE NOT NULL,
                variant_key TEXT NOT NULL,
                event_name TEXT NOT NULL,
                users INT NOT NULL,
                events INT NOT NULL,
                PRIMARY KEY (experiment_id, rollup_date, variant_key, event_name)
            );

            CREATE INDEX IF NOT EXISTS idx_experiment_events_lookup
                ON experiment_events(experiment_key, event_name, variant_key);
            CREATE INDEX IF NOT EXISTS idx_experiment_assignments_lookup
                ON experiment_assignments(experiment_id, variant_key);

            CREATE TABLE IF NOT EXISTS recommendation_category_affinity (
                user_id TEXT NOT NULL,
                category_id BIGINT NOT NULL,
                score DOUBLE PRECISION NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, category_id)
            );
            CREATE INDEX IF NOT EXISTS idx_recommendation_affinity_user
                ON recommendation_category_affinity(user_id, score DESC);
            ALTER TABLE recommendation_category_affinity
                ADD COLUMN IF NOT EXISTS click_count INT NOT NULL DEFAULT 0;
            ALTER TABLE recommendation_category_affinity
                ADD COLUMN IF NOT EXISTS last_clicked_at TIMESTAMPTZ;

            CREATE TABLE IF NOT EXISTS recommendation_item_events (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                surface TEXT NOT NULL,
                taca_item_id BIGINT NOT NULL,
                event_type TEXT NOT NULL CHECK (event_type IN ('exposure', 'click')),
                category_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_recommendation_item_events_user_time
                ON recommendation_item_events(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS promotion_funnel_events (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT,
                event_name TEXT NOT NULL,
                source TEXT,
                product_key TEXT,
                taca_item_id BIGINT,
                properties JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_promotion_funnel_events_time
                ON promotion_funnel_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_promotion_funnel_events_user_time
                ON promotion_funnel_events(user_id, created_at DESC);

            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS unit TEXT NOT NULL DEFAULT 'user';
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS alpha DOUBLE PRECISION NOT NULL DEFAULT 0.05;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS power DOUBLE PRECISION NOT NULL DEFAULT 0.8;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS baseline_rate DOUBLE PRECISION;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS mde DOUBLE PRECISION;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS min_sample_size INT;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS analysis_plan JSONB NOT NULL DEFAULT '{}'::jsonb;
            ALTER TABLE experiment_assignments ADD COLUMN IF NOT EXISTS first_exposed_at TIMESTAMPTZ;
            ALTER TABLE experiment_events ADD COLUMN IF NOT EXISTS event_id TEXT;
            ALTER TABLE experiment_events ADD COLUMN IF NOT EXISTS source TEXT;
            CREATE UNIQUE INDEX IF NOT EXISTS uq_experiment_events_event_id
                ON experiment_events(event_id) WHERE event_id IS NOT NULL;
            """
        )
