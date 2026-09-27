import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.app import app
from app.services import product_snapshot as store, promotion_settings as settings
from app.services.product_collection_status import summary


class CollectionStatusTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"MENU_DATA_DIR": tmp.name, "ADMIN_USERNAME": "test-admin",
                                    "ADMIN_PASSWORD": "test-password", "TOSS_PUBLISHER_ID": "test"})
        env.start()
        self.addCleanup(env.stop)

    def test_auth_no_network_and_no_internal_identifiers(self):
        store.write({"day": str(datetime.now(store.KST).date()), "status": "quota_exceeded",
                     "blocked": True, "reserved_products": 30, "private": "must-not-expose"},
                    "product_collection_state.json")
        client = TestClient(app)  # No lifespan / production database connection.
        self.addCleanup(client.close)
        with patch("requests.get", side_effect=AssertionError("external request")), \
             patch("requests.post", side_effect=AssertionError("external request")):
            self.assertEqual(client.get("/admin/promotion-settings/collection-status").status_code, 401)
            response = client.get("/admin/promotion-settings/collection-status", auth=("test-admin", "test-password"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertNotIn("must-not-expose", response.text)
        self.assertEqual(response.json()["reserved_today"], 30)

    def test_blocked_today_schedules_tomorrow_and_resets_day_count(self):
        now = datetime(2026, 9, 18, 12, tzinfo=store.KST)
        store.write({"day": "2026-09-18", "status": "quota_exceeded", "blocked": True,
                     "reserved_products": 30}, "product_collection_state.json")
        result = summary(now)
        self.assertTrue(result["blocked_today"])
        self.assertEqual(result["next_run_at"], "2026-09-19T00:05:00+09:00")
        result = summary(now + timedelta(days=1))
        self.assertFalse(result["blocked_today"])
        self.assertEqual(result["reserved_today"], 0)
        self.assertTrue(result["pending"])

    def test_fallback_is_distinct_from_usable_snapshot(self):
        settings.save_settings(settings.Settings(collections={
            "food": settings.CollectionSettings(label="먹거리", message_text="자취생 먹을거 핫딜",
                products=[settings.Product(title="등록 상품", url="https://toss.im/_m/test")]),
            "living": settings.CollectionSettings(label="꿀템", message_text="자취생 꿀템")}))
        rows = {row["id"]: row for row in summary()["collections"]}
        self.assertEqual(rows["food"]["serving"], "fallback")
        self.assertEqual(rows["today_deals"]["serving"], "empty")
        store.write({"updated_at": datetime.now(store.KST).isoformat(),
                     "items": {"1": {"tacaItemId": 1, "categoryIds": [1], "displayName": "상품",
                                      "displayPrice": 100, "thumbnailUrl": "https://example.com/image"}},
                     "links": {"1:test": "https://toss.im/_m/test"},
                     "categories": {"success": {"categories": [{"categoryId": 2, "displayName": "식품",
                         "children": [{"categoryId": 3, "displayName": "간식", "children": [
                             {"categoryId": 1, "displayName": "과자"}]}]}]}}, "lists": {}})
        rows = {row["id"]: row for row in summary()["collections"]}
        self.assertEqual(rows["food"]["serving"], "snapshot")
        self.assertEqual(rows["food"]["available_count"], 1)
