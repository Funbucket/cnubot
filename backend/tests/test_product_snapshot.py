import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.jobs import collect_products as job
from app.services import product_snapshot as store, toss_sharelink as api, promotions


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = patch.dict(os.environ, {"MENU_DATA_DIR": self.tmp.name, "TOSS_PUBLISHER_ID": "test"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.now = datetime.now(store.KST)

    def snapshot(self):
        return {"updated_at": self.now.isoformat(),
                "items": {str(i): {"tacaItemId": i, "displayName": str(i), "displayPrice": 100,
                                    "thumbnailUrl": "https://example.com/image.jpg"} for i in range(1, 19)},
                "lists": {"/openapi/products/today-deals": list(range(1, 19)),
                          "/openapi/products/best-selling": list(range(1, 19))},
                "links": {str(i) + ":test": "https://toss.im/_m/test" for i in range(1, 19)}}

    def test_requests_read_disk_without_network_and_rotate_multiple_rounds(self):
        store.write(self.snapshot())
        recent = {}
        tick = 0

        async def exposure(user, surface, item_id, *args, **kwargs):
            recent[item_id] = tick

        async def run():
            nonlocal tick
            pages = []
            for tick in range(1, 8):
                pairs = await promotions.get_today_deal_products("test", force_refresh=True)
                pages.append([p["taca_item_id"] for _, p in pairs])
            self.assertEqual(pages[0], list(range(1, 7)))
            self.assertEqual(pages[1], list(range(7, 13)))
            self.assertEqual(pages[2], list(range(13, 19)))
            self.assertEqual(pages[:3], pages[3:6])
            self.assertEqual(pages[0], pages[6])
            self.assertEqual(len(await api.best_selling(100)), 18)
            self.assertIsNotNone(await api.detail(1))

        with patch.object(api.requests, "get", side_effect=AssertionError("external GET")), \
             patch.object(api.requests, "post", side_effect=AssertionError("external POST")), \
             patch.object(promotions.recommendations, "recent_item_ids", AsyncMock(side_effect=lambda *a, **k: dict(recent))), \
             patch.object(promotions.recommendations, "record_exposure", AsyncMock(side_effect=exposure)):
            asyncio.run(run())

    def test_expiry_and_successful_empty_list_do_not_resurrect_deals(self):
        data = self.snapshot()
        data["items"]["1"]["endAt"] = (self.now - timedelta(seconds=1)).isoformat()
        store.write(data)
        self.assertEqual(len(store.response("/openapi/products/today-deals")["success"]["items"]), 17)
        data["updated_at"] = (self.now - timedelta(days=1)).isoformat()
        store.write(data)
        self.assertEqual(store.response("/openapi/products/today-deals")["success"]["items"], [])
        self.assertTrue(store.response("/openapi/products/best-selling")["success"]["items"])
        data["updated_at"] = (self.now - timedelta(days=3)).isoformat()
        store.write(data)
        self.assertEqual(store.response("/openapi/products/best-selling")["success"]["items"], [])

    def test_food_and_living_keep_rotating_after_exhaustion(self):
        food_tree = {i: ["식품", "분류" + str(i), "품목" + str(i)] for i in range(1, 7)}
        living_tree = dict(enumerate([
            ["생활용품", "세제", "세탁세제"], ["주방용품", "식기", "컵"],
            ["가전/디지털", "컴퓨터", "키보드"], ["문구/오피스", "필기", "펜"],
            ["뷰티", "헤어", "샴푸"], ["생활용품", "화장지/물티슈", "화장지"],
        ], 1))
        for collection, tree in (("food", food_tree), ("living", living_tree)):
            with self.subTest(collection=collection):
                candidates = [dict(self.snapshot()["items"][str(i)], categoryIds=[(i - 1) % 6 + 1])
                              for i in range(1, 19)]
                recent = {}
                tick = 0

                async def record(user, surface, item_id, *a, **kw):
                    recent[item_id] = tick

                async def run():
                    nonlocal tick
                    pages = []
                    for tick in range(1, 8):
                        pairs = await promotions.get_live_toss_products(
                            "test", collection_id=collection, limit=6, force_algorithm=True)
                        pages.append({p["taca_item_id"] for _, p in pairs})
                    self.assertTrue(all(len(p) == 6 for p in pages))
                    self.assertEqual(len(set.union(*pages[:3])), 18)
                    self.assertEqual(pages[:3], pages[3:6])
                    self.assertEqual(pages[0], pages[6])

                with patch.object(promotions, "_candidate_pool", AsyncMock(return_value=candidates)), \
                     patch.object(api, "categories", AsyncMock(return_value=tree)), \
                     patch("app.services.product_cache.detail", AsyncMock(side_effect=lambda cid: candidates[cid - 1])), \
                     patch("app.services.product_cache.link", AsyncMock(return_value="https://toss.im/_m/test")), \
                     patch.object(promotions.recommendations, "category_affinity", AsyncMock(return_value={})), \
                     patch.object(promotions.recommendations, "recent_item_ids", AsyncMock(side_effect=lambda *a, **k: dict(recent))), \
                     patch.object(promotions.recommendations, "record_exposure", AsyncMock(side_effect=record)):
                    asyncio.run(run())

    def test_quota_failure_keeps_snapshot_and_stops_retries_after_restart(self):
        data = self.snapshot()
        store.write(data)
        with patch.object(job, "slot", return_value="test-slot"), \
             patch.object(job.time, "sleep"), \
             patch.object(api, "_get_live_sync", side_effect=api.TossSharelinkError("SHARELINK_OPENAPI_QUOTA_EXCEEDED")) as fetch:
            self.assertEqual(job.collect(), "quota_exceeded")
            self.assertEqual(job.collect(), "not_due")
            fetch.assert_called_once()
        self.assertEqual(store.read(), data)

    def test_batch_publishes_lists_and_links_and_only_once_per_slot(self):
        product = self.snapshot()["items"]["1"]

        def get(path, params=None):
            if path.endswith("categories"):
                return {"success": {"categories": []}}
            return {"success": {"items": [product]}}

        with patch.object(job, "slot", return_value="test-slot"), \
             patch.object(job.time, "sleep"), \
             patch.object(api, "_get_live_sync", side_effect=get) as fetch, \
             patch.object(api, "_post_live_sync", return_value={"success": {"shortUrl": "https://toss.im/_m/test"}}) as links:
            self.assertEqual(job.collect(), "ok")
            self.assertEqual(job.collect(), "not_due")
            self.assertEqual(fetch.call_count, 3)
            links.assert_called_once()
        self.assertEqual(store.read( job.STATE)["reserved_products"], 130)
        self.assertEqual(store.read()["links"]["1:test"], "https://toss.im/_m/test")
