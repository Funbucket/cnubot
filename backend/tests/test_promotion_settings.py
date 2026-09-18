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
        settings._market_cache.clear()
        settings._market_locks.clear()
        self.enrichment = patch.object(settings, "enrich_product", side_effect=lambda p:p)
        self.enrichment.start()
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"MENU_DATA_DIR": self.directory.name,
            "ADMIN_USERNAME": "test-admin", "ADMIN_PASSWORD": "test-password",
            "PROMOTION_TRACKING_SECRET": "test-only-secret"})
        self.env.start()
        self.client = TestClient(app)  # No lifespan: never initialize the production DB.
        self.auth = ("test-admin", "test-password")
        self.headers = {"X-Promotion-Editor": "1"}

    def tearDown(self):
        self.enrichment.stop()
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
        self.assertEqual(settings.fixed_products(read)[0][1]["button_label"], settings.FIXED_PRODUCT_BUTTON_LABEL)
        with self.assertRaises(ValueError):
            settings.save_settings(initial)
        # read_settings fills collections in for legacy files; the stored data must not change.
        self.assertEqual(settings.read_settings().model_dump(exclude={"collections"}),
                         saved.model_dump(exclude={"collections"}))

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
        self.assertEqual(settings.read_collection("food").label, "🍱 자취생 먹을거")
        self.assertEqual(settings.read_collection("living").label, "자취생 꿀템")
        settings.save_settings(settings.Settings(collections={
            "food": settings.CollectionSettings(label="하이뮨 가격 보기", message_text="하이뮨 특가",
                                                mode="fixed", products=[self.product()]),
            "living": settings.CollectionSettings(label="하이뮨 18개 확인", message_text="자취생 꿀템")}))
        button = promotions.create_toss_promotion_button()
        reply = promotions.create_toss_promotion_quick_reply(KakaoJsonResponse())
        self.assertEqual(button["label"], "하이뮨 가격 보기")
        self.assertEqual(button["messageText"], "하이뮨 특가")
        self.assertEqual(button["extra"]["button_label"], button["label"])
        self.assertEqual(reply["label"], "하이뮨 18개 확인")
        self.assertEqual(reply["messageText"], "자취생 꿀템")

    def test_card_without_image_is_valid_text_card_and_no_fabricated_price(self):
        pairs = settings.fixed_products(settings.Settings(mode="fixed", products=[self.product()]))
        response = promotions.create_toss_shopping_list_response([p[1] for p in pairs])
        carousel = response["template"]["outputs"][1]["carousel"]
        self.assertEqual(carousel["type"], "textCard")
        self.assertNotIn("price", carousel["items"][0])
        self.assertEqual(response["template"]["outputs"][0]["simpleText"]["text"], settings.FIXED_PROMOTION_INTRO)

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

    def test_collection_adds_refresh_quick_reply(self):
        fixed = settings.Settings(
            mode="fixed",
            products=[self.product(str(i), image_url="https://shopping.toss.im/a.jpg") for i in range(6)],
        )
        products = [product for _, product in settings.fixed_products(fixed)]
        response = promotions.create_toss_shopping_list_response(products, collection_id="food")
        replies = response["template"]["quickReplies"]

        self.assertEqual([reply["label"] for reply in replies], ["자취생 꿀템", "새로고침"])
        self.assertEqual(replies[1]["extra"]["source"], "promotion_refresh")
        self.assertEqual(replies[0]["messageText"], "자취생 꿀템")

    def test_short_collection_also_adds_refresh_quick_reply(self):
        fixed = settings.Settings(
            mode="fixed",
            products=[self.product(str(i), image_url="https://shopping.toss.im/a.jpg") for i in range(5)],
        )
        products = [product for _, product in settings.fixed_products(fixed)]
        response = promotions.create_toss_shopping_list_response(products, collection_id="food")

        self.assertEqual([reply["label"] for reply in response["template"]["quickReplies"]], ["자취생 꿀템", "새로고침"])

    def test_today_deals_does_not_repeat_collection_and_adds_refresh(self):
        products = [{"title": str(i), "image_url": "https://shopping.toss.im/a.jpg",
                     "price": 100, "original_price": 200, "discount": 100,
                     "discount_rate": 50, "url": "https://toss.im/_m/" + str(i)}
                    for i in range(6)]
        response = promotions.create_toss_shopping_list_response(products, collection_id="today_deals")

        replies = response["template"]["quickReplies"]
        self.assertEqual([reply["label"] for reply in replies], ["🍱 자취생 먹을거", "자취생 꿀템", "새로고침"])
        self.assertEqual(replies[-1]["messageText"], "오늘 특가")

    def test_today_deals_keeps_collection_navigation_and_refresh_when_short(self):
        products = [{"title": str(i), "image_url": "https://shopping.toss.im/a.jpg",
                     "price": 100, "original_price": 200, "discount": 100,
                     "discount_rate": 50, "url": "https://toss.im/_m/" + str(i)}
                    for i in range(5)]
        response = promotions.create_toss_shopping_list_response(products, collection_id="today_deals")
        replies = response["template"]["quickReplies"]
        self.assertEqual([reply["label"] for reply in replies], [
            "🍱 자취생 먹을거", "자취생 꿀템", "새로고침"
        ])
        self.assertEqual(replies[-1]["messageText"], "오늘 특가")

    def test_today_deals_rotates_past_exposures_before_limiting(self):
        items = [{
            "tacaItemId": index,
            "displayName": f"오늘 특가 {index}",
            "displayPrice": 100,
            "originalPrice": 200,
            "discountRate": 50,
            "thumbnailUrl": f"https://example.com/{index}.jpg",
            "categoryIds": [],
        } for index in range(1, 9)]
        recent = [{}, {index: object() for index in range(1, 7)}]
        with patch.object(promotions.toss_sharelink, "today_deals", new=AsyncMock(return_value=items)), \
             patch("app.services.product_cache.link", new=AsyncMock(side_effect=lambda item_id: f"https://toss.im/_m/{item_id}")), \
             patch.object(promotions.recommendations, "recent_item_ids", new=AsyncMock(side_effect=recent)), \
             patch.object(promotions.recommendations, "record_exposure", new=AsyncMock()):
            first = asyncio.run(promotions.get_today_deal_products("test-user", limit=6))
            second = asyncio.run(promotions.get_today_deal_products("test-user", limit=6))

        self.assertEqual([product[1]["taca_item_id"] for product in first], list(range(1, 7)))
        self.assertEqual([product[1]["taca_item_id"] for product in second], [7, 8])

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
        self.assertIn("모든 변경사항 저장", page.text)

    def test_preview_and_chat_use_identical_commerce_card_prices(self):
        item = self.product(taca_item_id=149101033, image_url="https://shopping.toss.im/a.jpg")
        value = settings.Settings(mode="fixed", products=[item])
        settings.save_settings(value)
        detail = {"tacaItemId":149101033,"displayPrice":19900,"originalPrice":55800,"discountRate":64,"isSoldOut":False}
        with patch.object(promotions.toss_sharelink, "detail", new_callable=AsyncMock, return_value=detail) as api:
            preview = self.client.post("/admin/promotion-settings/preview", auth=self.auth,
                headers=self.headers, json=value.model_dump())
            response = self.client.post("/promotions/toss-shopping")
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["response"], response.json())
        card = response.json()["template"]["outputs"][1]["carousel"]
        self.assertEqual(card["type"], "commerceCard")
        self.assertEqual(card["items"][0]["price"], 55800)
        self.assertEqual(card["items"][0]["discountedPrice"], 19900)
        self.assertEqual(card["items"][0]["discountRate"], 64)
        self.assertEqual(card["items"][0]["description"], "")
        self.assertEqual(card["items"][0]["title"], item.title)
        api.assert_awaited_once()

    def test_price_refresh_and_failure_never_use_expired_price(self):
        item = self.product(taca_item_id=1)
        async def run():
            with patch.object(promotions.toss_sharelink, "detail", new_callable=AsyncMock,
                              return_value={"tacaItemId":1,"displayPrice":10000,"originalPrice":20000,"discountRate":50}) as api:
                first = await settings.market_product(item)
                await settings.market_product(item)
                self.assertEqual(api.await_count,1)
                api.return_value["displayPrice"] = 9000
                changed = await settings.market_product(item,force=True)
                self.assertEqual(changed["price"],9000)
                self.assertEqual(first["price"],10000)
                api.side_effect = RuntimeError("unavailable")
                failed = await settings.market_product(item,force=True)
                self.assertNotIn("price",failed)
                self.assertTrue(failed["price_error"])
        asyncio.run(run())

    def test_sold_out_is_visible_and_not_advertised_as_available(self):
        product = {**self.product().model_dump(),"selection_mode":"fixed","price":1000,
                   "original_price":2000,"discount_rate":50,"discount":1000,"is_sold_out":True}
        card = promotions.create_toss_shopping_list_response([product])["template"]["outputs"][1]["carousel"]
        self.assertEqual(card["type"],"textCard")
        self.assertTrue(card["items"][0]["description"].startswith("품절"))

    def test_market_product_carries_the_toss_rating(self):
        item = self.product(taca_item_id=1)
        async def run():
            with patch.object(promotions.toss_sharelink, "detail", new_callable=AsyncMock,
                              return_value={"tacaItemId":1,"displayPrice":10000,"originalPrice":20000,
                                            "discountRate":50,"reviewScore":4.6,"reviewCount":820}):
                resolved = await settings.market_product(item, force=True)
                self.assertEqual(resolved["review_score"], 4.6)
                self.assertEqual(resolved["review_count"], 820)
        asyncio.run(run())

    def test_carousel_puts_unit_prices_ahead_of_the_rating(self):
        product = {**self.product().model_dump(),"selection_mode":"fixed","price":7500,
                   "original_price":29900,"discount_rate":74,"discount":22400,
                   "image_url":"https://example.com/a.jpg","show_unit_price":True,"unit_count":10,
                   "review_score":4.6,"review_count":820}
        card = promotions.create_toss_shopping_list_response([product])["template"]["outputs"][1]["carousel"]
        self.assertEqual(card["items"][0]["description"], "🏷️ 1개당 750원\n⭐️ 4.6 (820)")

    def test_algorithm_carousel_uses_the_fixed_product_description_format(self):
        product = {"title": "생수 500ml 2개", "selection_mode": "algorithm",
                   "price": 1800, "original_price": 3000, "discount": 1200,
                   "discount_rate": 40, "image_url": "https://example.com/a.jpg",
                   "url": "https://example.com/product",
                   "review_score": 4.6, "review_count": 820,
                   "show_unit_price": True, "unit_count": 2,
                   "show_gram_price": True, "total_weight_g": 1000}
        card = promotions.create_toss_shopping_list_response([product])["template"]["outputs"][1]["carousel"]
        self.assertEqual(card["items"][0]["description"],
                         "🏷️ 1개당 900원\n⚖️ 100g당 180원\n⭐️ 4.6 (820)")

    def test_automatic_product_title_derives_unit_and_weight_fields(self):
        product = promotions._add_automatic_merchandising_fields({
            "title": "닭가슴살 1kg 2개", "price": 10000,
        })
        self.assertEqual(product["unit_count"], 2)
        self.assertEqual(product["total_weight_g"], 2000)
        self.assertTrue(product["show_unit_price"])
        self.assertTrue(product["show_gram_price"])


if __name__ == "__main__":
    unittest.main()
