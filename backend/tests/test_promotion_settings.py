import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError
from app.app import app
from app.services import promotion_settings as settings, promotions
from app.utils.kakao_json_response import KakaoJsonResponse

SHARE = ("✱ " + settings.DISCLOSURE + "\n"
         "일동후디스 하이뮨 프로틴 밸런스 액티브 밤티라미수 제로, 250ml, 18개\n"
         "https://toss.im/_m/l6bqsMls")


class PromotionSettingsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MENU_DATA_DIR": self.directory.name,
            "ADMIN_USERNAME": "test-admin", "ADMIN_PASSWORD": "test-password",
            "PROMOTION_TRACKING_SECRET": "test-only-secret"})
        self.env.start()
        self.client = TestClient(app)  # No lifespan: never initialize the production DB.
        self.auth = ("test-admin", "test-password")
        self.headers = {"X-Promotion-Editor": "1"}

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.directory.cleanup()

    def product(self, suffix="l6bqsMls", **kwargs):
        return settings.Product(title="하이뮨 18개", url="https://toss.im/_m/"+suffix, **kwargs)

    def test_parse_full_share_keeps_affiliate_url_and_removes_disclosure(self):
        product = settings.parse_share_text(SHARE)
        self.assertTrue(product.title.startswith("일동후디스"))
        self.assertNotIn("수수료", product.title)
        self.assertEqual(product.url, "https://toss.im/_m/l6bqsMls")

    def test_rejects_bad_hosts_and_multiple_links(self):
        for url in ["http://toss.im/_m/abc", "https://toss.im.evil.org/_m/abc",
                    "https://toss.im@127.0.0.1/_m/abc", "https://localhost/x",
                    "https://toss.im/_m/a https://toss.im/_m/b"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                settings.parse_share_text(url)

    def test_durable_order_hide_and_conflict(self):
        initial = settings.Settings(mode="fixed", products=[self.product("second"), self.product("hidden", enabled=False), self.product("first")])
        saved = settings.save_settings(initial)
        self.assertEqual(saved.revision, 1)
        read = settings.read_settings()
        self.assertEqual([p[1]["url"].split("/")[-1] for p in settings.fixed_products(read)], ["second", "first"])
        with self.assertRaises(ValueError):
            settings.save_settings(initial)
        self.assertEqual(settings.read_settings(), saved)

    def test_empty_fixed_and_duplicate_and_too_many_and_long_labels_rejected(self):
        for value in [{"mode": "fixed"}, {"products": [self.product(), self.product()]},
                      {"products": [self.product(str(i)) for i in range(7)]},
                      {"menu_button_label": "가"*15}]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                settings.Settings(**value)

    def test_admin_auth_and_cross_site_protection(self):
        self.assertEqual(self.client.get("/admin/promotion-settings").status_code, 401)
        self.assertEqual(self.client.put("/admin/promotion-settings", auth=self.auth, json={}).status_code, 403)
        response = self.client.put("/admin/promotion-settings", auth=self.auth, headers=self.headers,
            json={"mode":"fixed","products":[self.product().model_dump()]})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.get("/admin/promotion-settings", auth=self.auth)
        self.assertEqual(response.json()["mode"], "fixed")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(self.client.put("/admin/promotion-settings", auth=self.auth, headers=self.headers,
            json={"mode":"fixed","products":[self.product().model_dump()]}).status_code, 409)

    def test_parse_network_failure_still_returns_product(self):
        with patch.object(settings, "enrich_product", side_effect=RuntimeError):
            response = self.client.post("/admin/promotion-settings/parse", auth=self.auth,
                headers=self.headers, json={"text":SHARE})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["warning"])
        self.assertEqual(response.json()["product"]["url"], "https://toss.im/_m/l6bqsMls")

    def test_fixed_bypasses_algorithm_even_if_analytics_fails(self):
        settings.save_settings(settings.Settings(mode="fixed", products=[self.product("first"), self.product("second")]))
        with patch.object(promotions, "_candidate_pool", new_callable=AsyncMock) as candidates, \
             patch.object(promotions.recommendations, "record_exposure", new_callable=AsyncMock, side_effect=RuntimeError):
            products = asyncio.run(promotions.get_live_toss_products("test-user", limit=6))
        candidates.assert_not_called()
        self.assertEqual([p[1]["url"].split("/")[-1] for p in products], ["first", "second"])

    def test_switch_back_to_algorithm_preserves_draft(self):
        value = settings.save_settings(settings.Settings(mode="fixed", products=[self.product()]))
        value.mode = "algorithm"
        settings.save_settings(value)
        with patch.object(promotions, "_candidate_pool", new_callable=AsyncMock, return_value=[]) as candidates:
            self.assertEqual(asyncio.run(promotions.get_live_toss_products()), [])
        candidates.assert_awaited_once()
        self.assertEqual(len(settings.read_settings().products), 1)

    def test_editable_entry_buttons_and_defaults(self):
        settings.save_settings(settings.Settings(mode="fixed", menu_button_label="하이뮨 가격 보기",
            quick_reply_label="하이뮨 18개 확인", products=[self.product()]))
        button = promotions.create_toss_promotion_button()
        reply = promotions.create_toss_promotion_quick_reply(KakaoJsonResponse())
        self.assertEqual(button["label"], "하이뮨 가격 보기")
        self.assertEqual(button["extra"]["button_label"], button["label"])
        self.assertEqual(reply["label"], "하이뮨 18개 확인")

    def test_card_without_image_is_valid_text_card_and_no_fabricated_price(self):
        pairs = settings.fixed_products(settings.Settings(mode="fixed", products=[self.product()]))
        response = promotions.create_toss_shopping_list_response([p[1] for p in pairs])
        carousel = response["template"]["outputs"][1]["carousel"]
        self.assertEqual(carousel["type"], "textCard")
        self.assertNotIn("price", carousel["items"][0])
        self.assertIn(settings.DISCLOSURE, response["template"]["outputs"][0]["simpleText"]["text"])

    def test_image_cards_have_thumbnail_and_title_limit_and_order(self):
        data = settings.Settings(mode="fixed", products=[self.product(str(i), image_url="https://shopping.toss.im/a.jpg") for i in range(6)])
        products = [p[1] for p in settings.fixed_products(data)]
        products[0]["title"] = "가" * 100
        response = promotions.create_toss_shopping_list_response(products)
        outputs = response["template"]["outputs"]
        self.assertEqual(len(outputs), 3)
        self.assertEqual(outputs[1]["carousel"]["type"], "basicCard")
        self.assertEqual(len(outputs[1]["carousel"]["items"][0]["title"]), 50)
        self.assertEqual(outputs[2]["carousel"]["items"][0]["buttons"][0]["webLinkUrl"], "https://toss.im/_m/3")

    def test_old_click_keeps_original_link_and_metadata_after_edit(self):
        product = self.product()
        key = settings.product_key(product.url)
        token = promotions.create_tracking_token("test-user", key, target_url=product.url,
            product_snapshot={"title":"원래 상품명", "button_label":"원래 버튼", "settings_revision":1})
        with patch("app.routers.promotions.recommendations.record_category_click", new_callable=AsyncMock), \
             patch("app.routers.promotions.experiments.record_funnel_event", new_callable=AsyncMock) as event:
            response = self.client.get("/promotions/toss-shopping/click", params={"token":token}, follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], product.url)
        self.assertEqual(event.call_args.kwargs["properties"]["product_name"], "원래 상품명")
        self.assertEqual(event.call_args.kwargs["properties"]["product_button_label"], "원래 버튼")
        self.assertEqual(self.client.get("/promotions/toss-shopping/click", params={"token":token+"x"}).status_code, 400)

    def test_fixed_endpoint_and_editor_page(self):
        settings.save_settings(settings.Settings(mode="fixed", products=[self.product()]))
        response = self.client.post("/promotions/toss-shopping")
        self.assertEqual(response.status_code, 200)
        item = response.json()["template"]["outputs"][1]["carousel"]["items"][0]
        self.assertEqual(item["buttons"][0]["webLinkUrl"], self.product().url)
        page = self.client.get("/admin/recommendations", auth=self.auth)
        self.assertEqual(page.status_code, 200)
        self.assertIn("저장하고 적용", page.text)


if __name__ == "__main__":
    unittest.main()
