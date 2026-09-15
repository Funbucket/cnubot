import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from app.services.product_cache import AsyncCache


class ProductCacheTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_callers_share_fetch_and_receive_independent_values(self):
        cache = AsyncCache()
        async def fetch():
            await asyncio.sleep(.01)
            return {"price": 100}
        factory = AsyncMock(side_effect=fetch)
        results = await asyncio.gather(*(cache.get(1, factory) for _ in range(10)))
        factory.assert_awaited_once()
        results[0]["price"] = 999
        self.assertEqual((await cache.get(1, factory))["price"], 100)

    async def test_stale_fallback_stops_after_ten_minutes(self):
        cache = AsyncCache()
        factory = AsyncMock(return_value={"price": 100})
        with patch("app.services.product_cache.monotonic", return_value=0):
            await cache.get(1, factory)
        factory.side_effect = RuntimeError("offline")
        with patch("app.services.product_cache.monotonic", return_value=301):
            self.assertEqual((await cache.get(1, factory))["price"], 100)
        with patch("app.services.product_cache.monotonic", return_value=601):
            with self.assertRaises(RuntimeError):
                await cache.get(1, factory)

    async def test_sold_out_refresh_replaces_old_available_product(self):
        cache = AsyncCache()
        factory = AsyncMock(return_value={"isSoldOut": False})
        with patch("app.services.product_cache.monotonic", return_value=0):
            await cache.get(1, factory)
        factory.return_value = {"isSoldOut": True}
        with patch("app.services.product_cache.monotonic", return_value=301):
            self.assertTrue((await cache.get(1, factory))["isSoldOut"])

    async def test_cancelled_waiter_does_not_cancel_shared_refresh(self):
        cache = AsyncCache()
        started, finish = asyncio.Event(), asyncio.Event()
        async def fetch():
            started.set()
            await finish.wait()
            return 10
        first = asyncio.create_task(cache.get(1, fetch))
        await started.wait()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        finish.set()
        self.assertEqual(await cache.get(1, fetch), 10)

    async def test_capacity_is_bounded(self):
        cache = AsyncCache(capacity=2)
        for key in range(3):
            await cache.get(key, AsyncMock(return_value=key))
        self.assertEqual(list(cache.values), [1, 2])
