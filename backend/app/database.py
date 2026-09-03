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
    """Initialize application tables.

    The application currently has no database-backed features.
    """
    return
