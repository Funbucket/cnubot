"""Opt-in PostgreSQL checks using session-local temporary tables only."""
import os
import unittest
from datetime import date
from unittest.mock import patch

import asyncpg
from app.services import experiments


@unittest.skipUnless(os.getenv("RUN_PROMOTION_DB_TESTS") == "1", "opt-in PostgreSQL test")
class PromotionInsightsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        await self.conn.execute("""
            SET TIME ZONE 'UTC';
            CREATE TEMP TABLE user_events (
                user_id TEXT, event_name TEXT, created_at TIMESTAMPTZ,
                properties JSONB DEFAULT '{}', source TEXT, product_key TEXT,
                experiment_id BIGINT, variant_key TEXT
            );
            CREATE TEMP VIEW qualified_promotion_events AS SELECT * FROM pg_temp.user_events;
        """)
        conn = self.conn

        class Acquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                pass

        class Pool:
            def acquire(self):
                return Acquire()

        self.pool_patch = patch.object(experiments, "get_pool", return_value=Pool())
        self.pool_patch.start()

    async def asyncTearDown(self):
        self.pool_patch.stop()
        await self.conn.close()  # Temporary tables are destroyed with this connection.

    async def event(self, user, name, timestamp):
        await self.conn.execute("INSERT INTO pg_temp.user_events(user_id,event_name,created_at) VALUES($1,$2,$3::text::timestamptz)", user, name, timestamp)

    async def test_later_valid_click_counts_and_funnel_is_monotonic(self):
        await self.event("repeat", "promotion_entry_click", "2026-09-10 09:00+09")
        await self.event("repeat", "promotion_entry_exposure", "2026-09-10 10:00+09")
        await self.event("repeat", "promotion_entry_click", "2026-09-10 10:01+09")
        await self.event("repeat", "promotion_exposure", "2026-09-10 10:02+09")
        await self.event("repeat", "commerce_card_click", "2026-09-10 10:03+09")
        await self.event("invalid", "promotion_entry_click", "2026-09-10 09:00+09")
        await self.event("invalid", "promotion_entry_exposure", "2026-09-10 10:00+09")
        await self.event("invalid", "promotion_exposure", "2026-09-10 10:02+09")
        data = await experiments.get_promotion_insights(date(2026,9,10), date(2026,9,10))
        totals = data["totals"]
        self.assertEqual([totals[key] for key in ("entry_exposed_users", "entry_users", "exposed_users", "clicked_users")], [2,1,1,1])

    async def test_korean_day_boundaries_independent_of_database_timezone(self):
        await self.event("before", "promotion_entry_exposure", "2026-09-09 23:59:59+09")
        await self.event("first", "promotion_entry_exposure", "2026-09-10 00:00:00+09")
        await self.event("last", "promotion_entry_exposure", "2026-09-10 23:59:59+09")
        await self.event("after", "promotion_entry_exposure", "2026-09-11 00:00:00+09")
        data = await experiments.get_promotion_insights(date(2026,9,10), date(2026,9,10))
        self.assertEqual(data["totals"]["entry_exposed_users"], 2)
        self.assertEqual([row["day"] for row in data["daily"]], [date(2026,9,10)])
