"""Opt-in bundle transaction checks; all events live in a session-local temp table."""
import asyncio
import os
import unittest
from unittest.mock import patch

import asyncpg
from app.services import recommendations


@unittest.skipUnless(os.getenv("RUN_PROMOTION_DB_TESTS") == "1", "opt-in PostgreSQL test")
class BundleExposureDatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=1)
        async with self.pool.acquire() as conn:
            await conn.execute("""CREATE TEMP TABLE user_events (
                event_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, surface TEXT NOT NULL,
                taca_item_id BIGINT, event_name TEXT NOT NULL,
                product_key TEXT CHECK (product_key != 'rejected-product'),
                request_id TEXT, properties JSONB, created_at TIMESTAMPTZ DEFAULT NOW()
            )""")
        self.patcher = patch.object(recommendations, "get_pool", return_value=self.pool)
        self.patcher.start()
        self.items = [{"product_key":f"test-product-{i}","taca_item_id":i,
                       "category_ids":[i],"properties":{"position":i,"bundle_size":3}}
                      for i in range(1,4)]

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.pool.close()

    async def test_bundle_is_recorded_completely_then_next_request_is_capped(self):
        self.assertTrue(await recommendations.record_bundle_exposure("test-user","menu_inline_card",self.items,"first"))
        rows=await self.pool.fetch("SELECT product_key,request_id,properties->>'position' AS position FROM user_events ORDER BY product_key")
        self.assertEqual(len(rows),3)
        self.assertEqual({r['request_id'] for r in rows},{"first"})
        self.assertEqual({r['position'] for r in rows},{"1","2","3"})
        self.assertFalse(await recommendations.record_bundle_exposure("test-user","menu_inline_card",self.items,"second"))
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM user_events"),3)

    async def test_competing_calls_only_claim_one_slot(self):
        results=await asyncio.gather(*[
            recommendations.record_bundle_exposure("test-user","menu_inline_card",self.items,f"request-{i}")
            for i in range(2)])
        self.assertEqual(sum(results),1)
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM user_events"),3)

    async def test_failure_rolls_back_all_items_and_does_not_consume_slot(self):
        broken=[self.items[0],{**self.items[1],"product_key":"rejected-product"},self.items[2]]
        with self.assertRaises(asyncpg.CheckViolationError):
            await recommendations.record_bundle_exposure("test-user","menu_inline_card",broken,"broken")
        self.assertEqual(await self.pool.fetchval("SELECT count(*) FROM user_events"),0)
        self.assertTrue(await recommendations.record_bundle_exposure("test-user","menu_inline_card",self.items,"retry"))

    async def test_manual_preview_repeats_without_consuming_inline_cap(self):
        for i in range(2):
            self.assertTrue(await recommendations.record_bundle_exposure(
                "test-user","developer_bundle_preview",self.items,f"manual-{i}",daily_cap=False))
        self.assertFalse(await recommendations.has_promotion_exposure_today("test-user","menu_inline_card"))
        self.assertTrue(await recommendations.record_bundle_exposure("test-user","menu_inline_card",self.items,"inline"))

    async def test_existing_single_product_exposure_blocks_bundle(self):
        self.assertTrue(await recommendations.record_exposure_once_today(
            "test-user","menu_inline_card",99,[],product_key="existing",request_id="old"))
        self.assertFalse(await recommendations.record_bundle_exposure("test-user","menu_inline_card",self.items,"new"))
