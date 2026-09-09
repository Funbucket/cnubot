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

            -- The event log is the single source of truth for all user behaviour.
            -- Experiment and recommendation tables below are dimensions/aggregates,
            -- not separate event streams.
            CREATE TABLE IF NOT EXISTS user_events (
                id BIGSERIAL PRIMARY KEY,
                event_id TEXT,
                schema_version INT NOT NULL DEFAULT 1,
                user_id TEXT,
                anonymous_id TEXT,
                request_id TEXT,
                event_name TEXT NOT NULL,
                source TEXT,
                surface TEXT,
                experiment_id BIGINT REFERENCES experiments(id) ON DELETE SET NULL,
                experiment_key TEXT,
                variant_key TEXT,
                product_key TEXT,
                taca_item_id BIGINT,
                properties JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE UNIQUE INDEX IF NOT EXISTS uq_user_events_event_id
                ON user_events(event_id) WHERE event_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_user_events_user_time
                ON user_events(user_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_user_name_time
                ON user_events(user_id, event_name, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_name_time
                ON user_events(event_name, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_experiment
                ON user_events(experiment_id, variant_key, event_name, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_user_events_product
                ON user_events(product_key, event_name, created_at DESC);
            ALTER TABLE user_events ADD COLUMN IF NOT EXISTS request_id TEXT;
            CREATE INDEX IF NOT EXISTS idx_user_events_request_time
                ON user_events(request_id, created_at DESC);

            CREATE OR REPLACE VIEW qualified_promotion_events AS
            SELECT e.*,
                   CASE
                       WHEN e.event_name = 'promotion_entry_exposure' THEN 1
                       WHEN e.event_name = 'promotion_entry_click'
                            AND EXISTS (
                                SELECT 1 FROM user_events p
                                WHERE p.user_id = e.user_id
                                  AND p.event_name = 'promotion_entry_exposure'
                                  AND p.created_at <= e.created_at
                            ) THEN 2
                       WHEN e.event_name = 'promotion_exposure'
                            AND EXISTS (
                                SELECT 1 FROM user_events c
                                WHERE c.user_id = e.user_id
                                  AND c.event_name = 'promotion_entry_click'
                                  AND c.created_at <= e.created_at
                                  AND EXISTS (
                                      SELECT 1 FROM user_events p
                                      WHERE p.user_id = c.user_id
                                        AND p.event_name = 'promotion_entry_exposure'
                                        AND p.created_at <= c.created_at
                                  )
                            ) THEN 3
                       WHEN e.event_name IN ('promotion_click', 'promotion_button_click',
                                             'promotion_quick_reply_click',
                                             'promotion_block_click', 'commerce_card_click')
                            AND EXISTS (
                                SELECT 1 FROM user_events x
                                WHERE x.user_id = e.user_id
                                  AND x.event_name = 'promotion_exposure'
                                  AND x.created_at <= e.created_at
                                  AND EXISTS (
                                      SELECT 1 FROM user_events c
                                      WHERE c.user_id = x.user_id
                                        AND c.event_name = 'promotion_entry_click'
                                        AND c.created_at <= x.created_at
                                        AND EXISTS (
                                            SELECT 1 FROM user_events p
                                            WHERE p.user_id = c.user_id
                                              AND p.event_name = 'promotion_entry_exposure'
                                              AND p.created_at <= c.created_at
                                        )
                                  )
                            ) THEN 4
                   END AS funnel_stage
            FROM user_events e;

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

            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS unit TEXT NOT NULL DEFAULT 'user';
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS alpha DOUBLE PRECISION NOT NULL DEFAULT 0.05;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS power DOUBLE PRECISION NOT NULL DEFAULT 0.8;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS baseline_rate DOUBLE PRECISION;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS mde DOUBLE PRECISION;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS min_sample_size INT;
            ALTER TABLE experiments ADD COLUMN IF NOT EXISTS analysis_plan JSONB NOT NULL DEFAULT '{}'::jsonb;
            ALTER TABLE experiment_assignments ADD COLUMN IF NOT EXISTS first_exposed_at TIMESTAMPTZ;

            -- One-time compatibility migration from the old split event tables.
            DO $$ BEGIN
                IF to_regclass('public.experiment_events') IS NOT NULL THEN
                    INSERT INTO user_events
                        (event_id, schema_version, user_id, event_name, source,
                         experiment_id, experiment_key, variant_key, product_key,
                         properties, created_at)
                    SELECT event_id, 1, user_id, event_name, source,
                           experiment_id, experiment_key, variant_key,
                           properties->>'product_key', properties, created_at
                    FROM experiment_events
                    ON CONFLICT DO NOTHING;
                END IF;
                IF to_regclass('public.promotion_funnel_events') IS NOT NULL THEN
                    INSERT INTO user_events
                        (event_id, schema_version, user_id, event_name, source,
                         product_key, taca_item_id, properties, created_at)
                    SELECT event_id, schema_version, user_id, event_name, source,
                           product_key, taca_item_id, properties, created_at
                    FROM promotion_funnel_events
                    ON CONFLICT DO NOTHING;
                END IF;
                IF to_regclass('public.recommendation_item_events') IS NOT NULL THEN
                    INSERT INTO user_events
                        (user_id, event_name, surface, taca_item_id, properties, created_at)
                    SELECT user_id,
                           CASE WHEN event_type = 'exposure' THEN 'recommendation_exposure'
                                ELSE 'recommendation_click' END,
                           surface, taca_item_id,
                           jsonb_build_object('category_ids', category_ids), created_at
                    FROM recommendation_item_events;
                END IF;
            END $$;

            DROP TABLE IF EXISTS experiment_events;
            DROP TABLE IF EXISTS promotion_funnel_events;
            DROP TABLE IF EXISTS recommendation_item_events;
            DROP TABLE IF EXISTS meal_reactions;
            DROP TABLE IF EXISTS meal_snapshots;
            DROP TABLE IF EXISTS cafeteria_favorites;
            """
        )
