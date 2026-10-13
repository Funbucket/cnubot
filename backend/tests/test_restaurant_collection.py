import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.jobs.collect_restaurants import due
from app.schemas.restaurants import Catalog
from app.scrapers import restaurants as scraper
from app.services import restaurant_catalog as store, restaurants as service

NOW = datetime(2026, 10, 13, 12, tzinfo=ZoneInfo("Asia/Seoul"))
PLACE = {"id": "123", "place_name": "가상 식당", "address_name": "대전 유성구 어은동 1-1"}


def payload(*menus):
    return {"summary": {"confirm_id": "123", "name": "가상 식당", "status": "Y",
                        "category": {"name1": "음식점", "name2": "일식", "name": "일식집"},
                        "address": {"jibun": "어은동 1-1"}},
            "menu": {"menus": {"items": list(menus), "items_updated_at": "2025-05-01 12:00:00",
                               "photos": [{"private_test_profile": "must-not-save"}]}},
            "kakaomap_review": {"score_set": {"average_score": 4.3, "review_count": 26},
                                "reviews": [{"private_test_profile": "must-not-save", "text": "ignored"}]}}


class CollectionTest(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(store, "now_kst", return_value=NOW)
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.folder = tempfile.TemporaryDirectory(); self.addCleanup(self.folder.cleanup)
        env = patch.dict(os.environ, {"RESTAURANTS_DATA_PATH": str(Path(self.folder.name) / "catalog.json"),
                                     "KAKAO_REST_API_KEY": "test-only"})
        env.start(); self.addCleanup(env.stop)

    def test_extract_explicit_food_prices_and_aggregate_only_preserving_source_date(self):
        data = payload({"name": "돈가스 정식", "price": 12000}, {"name": "우동", "price": 8000},
            {"name": "콜라", "price": 3000}, {"name": "공기밥 추가", "price": 3000},
            {"name": "마라탕(100g)", "price": 2100, "desc": "7000원부터"},
            {"name": "어린이 돈가스", "price": 6000}, {"name": "2인 초밥 세트", "price": 30000},
            {"name": "초밥", "price": "시가"}, {"name": "회", "price": 18000},
            {"name": "런치코스(1인)", "price": 25000})
        item = scraper.parse_public_place(PLACE, "어은동", data, NOW)
        self.assertEqual({meal.name for meal in item.meals}, {"돈가스 정식", "우동", "런치코스(1인)"})
        self.assertEqual(item.rating.score, 4.3)
        self.assertEqual(item.rating.count, 26)
        self.assertEqual(item.origin, "kakao_public")
        self.assertEqual(item.meals[0].source_updated_on.isoformat(), "2025-05-01")
        self.assertEqual(item.meals[0].checked_on, NOW.date())
        self.assertNotIn("must-not-save", item.model_dump_json())
        catalog = Catalog(items=[item], ratings_enabled=True, rating_usage_basis="공개 장소 집계")
        _, response, _ = service.transition(None, "주변맛집 어은동 1만원대", catalog, "", NOW)
        card = response["template"]["outputs"][1]["carousel"]["items"][0]
        self.assertEqual(item.meals[0].source_updated_on.isoformat(), "2025-05-01")
        self.assertIn("카카오맵 등록 기준", response["template"]["outputs"][0]["simpleText"]["text"])

    def test_bad_identity_region_structure_fails_instead_of_empty_success(self):
        for data in [{}, payload({"name": "우동", "price": 8000})]:
            if data:
                data["summary"]["confirm_id"] = "other"
            with self.assertRaises(ValueError):
                scraper.parse_public_place(PLACE, "어은동", data, NOW)
        with self.assertRaises(ValueError):
            scraper.parse_public_place(PLACE, "궁동", payload({"name": "우동", "price": 8000}), NOW)

    def test_no_menu_or_closed_excluded_without_inventing_prices_or_ratings(self):
        self.assertIsNone(scraper.parse_public_place(PLACE, "어은동", payload(), NOW))
        no_menu_section = payload()
        no_menu_section.pop("menu")
        self.assertIsNone(scraper.parse_public_place(PLACE, "어은동", no_menu_section, NOW))
        delivery_only = payload()
        delivery_only["menu"] = {"yogiyo_menus": {"items": [{"name": "우동", "price": 8000}]}}
        self.assertIsNone(scraper.parse_public_place(PLACE, "어은동", delivery_only, NOW))
        malformed_menu = payload()
        malformed_menu["menu"] = {"menus": []}
        with self.assertRaises(ValueError):
            scraper.parse_public_place(PLACE, "어은동", malformed_menu, NOW)
        data = payload({"name": "우동", "price": 8000})
        data["summary"]["status"] = "N"
        self.assertIsNone(scraper.parse_public_place(PLACE, "어은동", data, NOW))
        data["summary"]["status"] = "Y"
        data["kakaomap_review"]["score_set"]["review_count"] = 0
        self.assertIsNone(scraper.parse_public_place(PLACE, "어은동", data, NOW).rating)

    def test_multiple_bands_survive_ten_menu_limit(self):
        data = payload(*[{"name": f"초밥 정식 {n}", "price": 4000 + n * 2000} for n in range(20)])
        item = scraper.parse_public_place(PLACE, "어은동", data, NOW)
        self.assertLessEqual(len(item.meals), 10)
        self.assertTrue(any(meal.total_price < 10000 for meal in item.meals))
        self.assertTrue(any(10000 <= meal.total_price < 20000 for meal in item.meals))
        self.assertTrue(any(meal.total_price >= 20000 for meal in item.meals))

    def test_manual_records_and_hidden_auto_records_are_preserved(self):
        auto = scraper.parse_public_place(PLACE, "어은동", payload({"name": "초밥", "price": 12000}), NOW)
        updated = auto.model_copy(update={"meals": [auto.meals[0].model_copy(update={"total_price": 14000})]})
        manual = auto.model_copy(update={"origin": "manual"})
        result = scraper.merge_results(Catalog(items=[manual]), {"123": updated}, NOW)
        self.assertEqual(result.items[0].meals[0].total_price, 12000)
        result = scraper.merge_results(Catalog(items=[auto.model_copy(update={"enabled": False})]), {"123": updated}, NOW)
        self.assertFalse(result.items[0].enabled)
        self.assertEqual(result.items[0].meals[0].total_price, 14000)
        self.assertEqual(scraper.merge_results(Catalog(items=[auto]), {}, NOW).items, [auto])
        self.assertEqual(scraper.merge_results(Catalog(items=[auto]), {"123": None}, NOW).items, [])

    def test_partial_failure_retains_previous_data_and_complete_failure_does_not_replace(self):
        original = scraper.parse_public_place(PLACE, "어은동", payload({"name": "초밥", "price": 12000}), NOW)
        store.save_catalog(Catalog(items=[original]))
        before = store.catalog_path().read_bytes()
        with patch.object(scraper, "discover", side_effect=request_error), patch.object(scraper.time, "sleep"):
            status = scraper.collect()
        self.assertEqual(status["status"], "failed")
        self.assertEqual(before, store.catalog_path().read_bytes())
        second = {**PLACE, "id": "456"}
        data = payload({"name": "우동", "price": 7000}); data["summary"]["confirm_id"] = "456"
        def discover(session, area, key, pages):
            if area != "어은동":
                raise RuntimeError("test connection failure")
            return [PLACE, second]
        with patch.object(scraper, "discover", side_effect=discover), patch.object(scraper, "_get_json", side_effect=[RuntimeError(), data]), patch.object(scraper.time, "sleep"):
            status = scraper.collect()
        self.assertEqual(status["status"], "partial")
        self.assertEqual(status["page_failures"], 1)
        self.assertEqual(len(store.read_catalog().items), 2)
        self.assertEqual(store.read_catalog().items[0].meals[0].total_price, 12000)

    def test_auto_enables_first_rating_source_but_keeps_operator_opt_out(self):
        item = scraper.parse_public_place(PLACE, "어은동", payload({"name": "초밥", "price": 12000}), NOW)
        first = scraper.merge_results(Catalog(), {"123": item}, NOW)
        self.assertTrue(first.ratings_enabled)
        second = scraper.merge_results(first.model_copy(update={"ratings_enabled": False}), {"123": item}, NOW)
        self.assertFalse(second.ratings_enabled)

    def test_discovery_excludes_other_cities_and_sends_key_only_to_official_api(self):
        with patch.object(scraper, "_get_json", return_value={"meta": {"is_end": True}, "documents": [PLACE, {**PLACE, "id": "987", "address_name": "다른 도시 어은동 1"}]}) as get:
            self.assertEqual(scraper.discover(object(), "어은동", "test-only"), [PLACE])
        self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "KakaoAK test-only"})
        self.assertTrue(get.call_args.args[1].startswith("https://dapi.kakao.com/"))

    def test_discovery_searches_multiple_food_types_and_deduplicates_places(self):
        def local_response(session, url, **kwargs):
            word = kwargs["params"]["query"].split()[-1]
            return {"meta": {"is_end": True}, "documents": [PLACE,
                {**PLACE, "id": str(1000 + scraper.SEARCH_WORDS.index(word))}]}
        with patch.object(scraper, "_get_json", side_effect=local_response) as get:
            places = scraper.discover(object(), "어은동", "test-only")
        self.assertEqual(len(places), len(scraper.SEARCH_WORDS) + 1)
        self.assertEqual(get.call_count, len(scraper.SEARCH_WORDS))
        self.assertEqual({call.kwargs["params"]["query"].split()[-1] for call in get.call_args_list},
                         set(scraper.SEARCH_WORDS))

    def test_schedule_refreshes_six_hour_success_and_retries_partial_after_half_hour(self):
        success = {"status": "ok", "last_success_at": NOW.isoformat(),
                   "areas": {area: {"status": "ok"} for area in scraper.AREAS}}
        self.assertFalse(due(NOW + timedelta(hours=5), success))
        self.assertTrue(due(NOW + timedelta(hours=6), success))
        self.assertTrue(due(NOW + timedelta(minutes=30), {**success, "status": "partial"}))
        failed = {**success, "status": "failed", "finished_at": NOW.isoformat(),
                  "last_success_at": (NOW - timedelta(hours=7)).isoformat()}
        self.assertFalse(due(NOW + timedelta(minutes=29), failed))
        self.assertTrue(due(NOW + timedelta(minutes=30), failed))
        self.assertTrue(due(NOW, {}))
        self.assertTrue(due(NOW, {**success, "areas": {"궁동": {}, "어은동": {}}}))


def request_error(*args):
    raise RuntimeError("test connection failure")


if __name__ == "__main__":
    unittest.main()
