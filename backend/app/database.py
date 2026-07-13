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
            CREATE TABLE IF NOT EXISTS meal_snapshots (
                meal_id TEXT PRIMARY KEY,
                place TEXT NOT NULL,
                place_name TEXT NOT NULL,
                day TEXT NOT NULL,
                meal_time TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                calorie TEXT,
                menu_items JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS meal_reactions (
                id BIGSERIAL PRIMARY KEY,
                meal_id TEXT NOT NULL REFERENCES meal_snapshots(meal_id)
                    ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                reaction TEXT NOT NULL CHECK (reaction IN ('positive', 'negative')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (meal_id, user_id)
            );

            CREATE INDEX IF NOT EXISTS idx_meal_reactions_meal_id
                ON meal_reactions(meal_id);

            CREATE TABLE IF NOT EXISTS cafeteria_favorites (
                id BIGSERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                place TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, place)
            );

            CREATE INDEX IF NOT EXISTS idx_cafeteria_favorites_user_id
                ON cafeteria_favorites(user_id);
            """
        )
