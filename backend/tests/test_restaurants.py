import asyncio
import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.app import app
from app.schemas.restaurants import Catalog, Rating, Restaurant
from app.services import cafeteria, restaurant_catalog as store, restaurants as service

NOW = datetime(2026, 10, 13, 12, tzinfo=ZoneInfo("Asia/Seoul"))
_clock = patch.object(store, "now_kst", return_value=NOW)


def setUpModule():
    _clock.start()


def tearDownModule():
    _clock.stop()


def item(index=0, *, price=9000, diners=1, area="궁동", cuisine="한식", enabled=True, age=0, rating=None):
    return Restaurant(id=f"test-{index}", name=f"테스트 식당 {index}", area=area, cuisine=cuisine,
        place_url=f"https://place.map.kakao.com/{index + 1}", enabled=enabled,
        reason="1인 주문 가능", evidence="테스트용 가상 확인 근거",
        meals=[{"name": "테스트 식사", "total_price": price, "diners": diners,
                "checked_on": (NOW - timedelta(days=age)).date(), "source": "가상 메뉴판"}], rating=rating)


def rating(score=4.2, days=0):
    return Rating(score=score, count=50, checked_at=NOW - timedelta(days=days))


def cards(response):
    return [card for output in response["template"]["outputs"] for card in output.get("carousel", {}).get("items", [])]


def messages(response):
    return [reply["messageText"] for reply in response["template"]["quickReplies"]]


class CatalogTest(unittest.TestCase):
    def test_price_band_boundaries_and_shared_meal_total(self):
        catalog = Catalog(items=[item(n, price=price) for n, price in enumerate([9999, 10000, 19999, 20000])]
                          + [item(10, price=19999, diners=2)])
        expected = {"1만원 미만": ["test-0"], "1만원대": ["test-1", "test-2", "test-10"], "2만원 이상": ["test-3"]}
        for budget, ids in expected.items():
            state, _, _ = service.transition(None, f"주변맛집 궁동 {budget}", catalog, "", NOW)
            self.assertEqual([row[0].id for row in service.candidates(catalog, state, NOW)], ids)

    def test_stale_future_hidden_and_wrong_region_are_excluded(self):
        future = item(5)
        future = future.model_copy(update={"meals": [future.meals[0].model_copy(update={"checked_on": (NOW + timedelta(days=1)).date()})]})
        catalog = Catalog(items=[item(), item(1, age=30), item(2, age=31), item(3, enabled=False),
                                 item(4, area="어은동"), future, item(6, area="죽동")])
        state, _, _ = service.transition(None, "주변맛집 궁동 1만원 미만", catalog, "", NOW)
        self.assertEqual([row[0].id for row in service.candidates(catalog, state, NOW)], ["test-0", "test-1"])

    def test_duplicate_places_and_bad_urls_and_fake_prices_rejected(self):
        first = item()
        same = item(1).model_copy(update={"place_url": first.place_url.replace("https:", "http:")})
        with self.assertRaises(ValidationError):
            Catalog(items=[first, same])
        for field, value in [("place_url", "https://place.map.kakao.com.evil.org/1"),
                             ("place_url", "https://example.com/1")]:
            with self.assertRaises(ValidationError):
                Restaurant.model_validate({**first.model_dump(), field: value})
        for price in [0, -1, True, "9000", 9000.5]:
            data = first.model_dump(); data["meals"][0]["total_price"] = price
            with self.assertRaises(ValidationError):
                Restaurant.model_validate(data)

    def test_rating_requires_usage_basis_and_aware_timestamp(self):
        with self.assertRaises(ValidationError):
            Catalog(ratings_enabled=True)
        for timestamp in [NOW.replace(tzinfo=None), NOW + timedelta(days=1)]:
            with patch.object(store, "now_kst", return_value=NOW), self.assertRaises(ValidationError):
                Rating(score=4.0, count=20, checked_at=timestamp)
        for score in [float("nan"), float("inf"), 5.1, 4.49]:
            with self.assertRaises(ValidationError):
                Rating(score=score, count=20, checked_at=NOW)

    def test_atomic_save_conflict_and_invalid_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"RESTAURANTS_DATA_PATH": str(Path(folder) / "catalog.json")}):
            payload = Catalog(items=[item()])
            saved = store.save_catalog(payload)
            self.assertEqual(saved.revision, 1)
            self.assertEqual(store.read_catalog(), saved)
            with self.assertRaises(ValueError):
                store.save_catalog(payload)
            store.catalog_path().write_text('{"broken": true}')
            before = store.catalog_path().read_bytes()
            self.assertEqual(store.safe_catalog().items, [])
            with self.assertRaises(ValueError):
                store.save_catalog(Catalog())
            self.assertEqual(before, store.catalog_path().read_bytes())

    def test_kakao_search_is_transient_and_does_not_invent_rating_or_menu(self):
        with patch.dict(os.environ, {"KAKAO_REST_API_KEY": "test-only"}), patch("requests.get") as get:
            get.return_value.json.return_value = {"documents": [{"place_name": "가상 검색 결과", "place_url": "http://place.map.kakao.com/1", "rating": 5}]}
            result = store.search_places("궁동 밥집")
            self.assertNotIn("rating", result[0])
            self.assertNotIn("price", result[0])
            self.assertEqual(get.call_args.kwargs["params"]["category_group_code"], "FD6")
            self.assertEqual(get.call_args.kwargs["headers"], {"Authorization": "KakaoAK test-only"})


class BrowseTest(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog(items=[item(n, cuisine=["한식", "일식", "중식"][n % 3]) for n in range(7)])

    def test_jukdong_selection_is_isolated_and_direct_budget_needs_no_session(self):
        catalog = Catalog(items=[item(0, area="어은동", price=12000), item(1, area="죽동", price=12000)])
        state, _, _ = service.transition(None, "주변맛집 어은동 1만원대", catalog, "hash", NOW)
        state, response, event = service.transition(state, "주변맛집 죽동 1만원대", catalog, "hash", NOW)
        self.assertEqual(state["area"], "죽동")
        self.assertEqual(event["place_ids"], ["test-1"])
        self.assertEqual(len(cards(response)), 1)
        _, response, _ = service.transition(None, "주변맛집 죽동 1만원대", catalog, "", NOW, can_browse=False)
        self.assertEqual(len(cards(response)), 1)
        _, response, _ = service.transition(None, "주변맛집 죽동", catalog, "", NOW, can_browse=False)
        self.assertEqual(messages(response)[:3], [f"주변맛집 죽동 {budget}" for budget in service.BUDGETS])

    def test_choose_three_distinct_cuisines_then_unseen_until_exhaustion(self):
        state, response, event = service.transition(None, "주변맛집 궁동 1만원 미만", self.catalog, "hash", NOW)
        self.assertEqual(len(cards(response)), 3)
        first = set(event["place_ids"])
        self.assertEqual(len({c["title"].split(" · ")[-1] for c in cards(response)}), 3)
        state, response, event = service.transition(state, service.MORE, self.catalog, "hash", NOW)
        self.assertFalse(first & set(event["place_ids"]))
        state, response, event = service.transition(state, service.MORE, self.catalog, "hash", NOW)
        self.assertEqual(event["count"], 1)
        self.assertEqual(response["template"]["quickReplies"][0]["label"], "🔄 다시 둘러보기")
        state, response, event = service.transition(state, service.MORE, self.catalog, "hash", NOW)
        self.assertEqual(event["count"], 3)
        self.assertIn("봤던 곳", response["template"]["outputs"][0]["simpleText"]["text"])

    def test_history_prevents_immediate_repeat_on_reentry_or_expired_session(self):
        state, _, event = service.transition(None, "주변맛집 궁동 1만원 미만", self.catalog, "hash", NOW)
        first = set(event["place_ids"])
        for clock in [NOW + timedelta(minutes=1), NOW + timedelta(minutes=31)]:
            _, _, next_event = service.transition(state, "주변맛집 궁동 1만원 미만", self.catalog, "hash", clock)
            self.assertFalse(first & set(next_event["place_ids"]))

    def test_unseen_places_take_priority_over_repeating_a_different_cuisine(self):
        catalog = Catalog(items=[item(n) for n in range(3)] + [item(3, cuisine="일식")])
        state, _ = service.prepare_state(None, NOW)
        state.update(area="궁동", budget="1만원 미만", history={"test-3": NOW.isoformat()})
        _, _, event = service.transition(state, service.MORE, catalog, "hash", NOW)
        self.assertEqual(set(event["place_ids"]), {"test-0", "test-1", "test-2"})

    def test_strict_rating_filter_excludes_unknown_stale_below_and_preserves_budget(self):
        catalog = Catalog(ratings_enabled=True, rating_usage_basis="테스트 이용 근거", items=[
            item(0, rating=rating(4.5)), item(1, rating=rating(4.0)), item(2, rating=rating(4.9, 8)),
            item(3), item(4, rating=rating(4.8), price=20000)])
        state, _, _ = service.transition(None, "주변맛집 궁동 1만원 미만", catalog, "hash", NOW)
        state, response, event = service.transition(state, "주변맛집 별점 4.5 이상", catalog, "hash", NOW)
        self.assertEqual(event["place_ids"], ["test-0"])
        self.assertEqual(state["budget"], "1만원 미만")
        self.assertIn("⭐ 4.5", cards(response)[0]["description"])
        changed = catalog.model_copy(update={"ratings_enabled": False})
        state, response, event = service.transition(state, service.MORE, changed, "hash", NOW)
        self.assertEqual(event["count"], 0)
        self.assertEqual(state["min_rating"], 4.5)
        self.assertIn("주변맛집 별점 전체", messages(response))

    def test_unavailable_ratings_hidden_and_not_claimed_as_applied(self):
        state, response, _ = service.transition(None, "주변맛집 궁동 1만원 미만", self.catalog, "hash", NOW)
        self.assertNotIn(service.RATING_MENU, messages(response))
        state, response, event = service.transition(state, "주변맛집 별점 4.0 이상", self.catalog, "hash", NOW)
        self.assertEqual(state["min_rating"], 0)
        self.assertIsNone(event)
        self.assertIn("찾을 수 없어요", response["template"]["outputs"][0]["simpleText"]["text"])

    def test_expired_or_missing_state_restarts_and_direct_budget_survives_without_db(self):
        state, _, _ = service.transition(None, "주변맛집 궁동 1만원 미만", self.catalog, "hash", NOW)
        for previous in [None, state]:
            _, response, event = service.transition(previous, service.MORE, self.catalog, "hash", NOW + timedelta(minutes=31))
            self.assertIsNone(event)
            self.assertEqual(len(cards(response)), 0)
            self.assertEqual(set(messages(response)), set(service.AREAS))
        _, response, _ = service.transition(None, "주변맛집 궁동 1만원 미만", self.catalog, "", NOW, can_browse=False)
        self.assertEqual(len(cards(response)), 3)
        self.assertNotIn(service.MORE, messages(response))

    def test_menu_does_not_consume_recommendations_and_uses_exact_registered_messages(self):
        catalog = Catalog(ratings_enabled=True, rating_usage_basis="테스트 이용 근거", items=[item(rating=rating())])
        state, _, _ = service.transition(None, "주변맛집 궁동 1만원 미만", catalog, "hash", NOW)
        before = copy.deepcopy(state["seen"])
        after, response, _ = service.transition(state, service.RATING_MENU, catalog, "hash", NOW)
        self.assertEqual(before, after["seen"])
        self.assertEqual(set(messages(response)), set(service.RATINGS))
        allowed = set().union(*service.ROUTE_MESSAGES.values())
        docs = (Path(__file__).resolve().parents[2] / "docs/kakao-message-routing.md").read_text()
        for route, utterances in service.ROUTE_MESSAGES.items():
            for utterance in utterances:
                _, response, _ = service.transition(state, utterance, catalog, "hash", NOW)
                self.assertTrue(set(messages(response)) <= allowed)
                self.assertIn(utterance, docs)

    def test_card_limits_and_shared_meal_cost_survive_extreme_values(self):
        raw = item(price=1000000, diners=3, rating=rating()).model_dump()
        raw.update(name="가" * 35, cuisine="나" * 10, reason="다" * 25)
        raw["meals"][0]["name"] = "라" * 35
        raw["rating"]["count"] = 100000000
        long = Restaurant.model_validate(raw)
        catalog = Catalog(items=[long], ratings_enabled=True, rating_usage_basis="테스트")
        _, response, _ = service.transition(None, "주변맛집 궁동 2만원 이상", catalog, "", NOW)
        card = cards(response)[0]
        self.assertLessEqual(len(card["title"]), 50)
        self.assertLessEqual(len(card["description"]), 128)
        self.assertIn("1,000,000원", card["description"])
        self.assertIn("333,334원", card["description"])
        self.assertIn("리뷰 100,000,000개", card["description"])

    def test_entry_button_requires_operator_enable_and_is_on_schedule_and_menu(self):
        for enabled in ["false", "true"]:
            with patch.dict(os.environ, {"RESTAURANTS_ENABLED": enabled}):
                schedule = cafeteria.create_schedule_response([])
                menu = cafeteria.create_no_menu_response("월요일", "기숙사")
                for response in [schedule, menu]:
                    self.assertEqual(service.HOME in messages(response), enabled == "true")
                    self.assertNotIn("학교혜택", messages(response))


class Transaction:
    def __init__(self, conn):
        self.conn = conn
        self.depth = 0

    async def __aenter__(self):
        # Test doubles serialize the outer transaction; inner blocks represent savepoints.
        if self.conn.owner is not asyncio.current_task():
            await self.conn.lock.acquire()
            self.conn.owner = asyncio.current_task()
        self.conn.depth += 1

    async def __aexit__(self, *args):
        self.conn.depth -= 1
        if self.conn.depth == 0:
            self.conn.owner = None
            self.conn.lock.release()


class Connection:
    def __init__(self):
        self.states, self.events = {}, {}
        self.lock = asyncio.Lock()
        self.depth = 0
        self.owner = None
        self.fail_events = False

    def transaction(self):
        return Transaction(self)

    async def execute(self, query, *args):
        if query.lstrip().startswith("INSERT INTO restaurant_browse_states"):
            self.states[args[0]] = json.loads(args[1])
        if query.lstrip().startswith("INSERT INTO restaurant_events"):
            if self.fail_events:
                raise RuntimeError("test analytics failure")
            self.events.setdefault(args[0], (args[1], args[2], args[3], json.loads(args[4])))

    async def fetchrow(self, query, key):
        return {"state": json.dumps(self.states[key])} if key in self.states else None


class Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return Acquire(self.conn)


class DatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_refreshes_are_isolated_and_do_not_repeat(self):
        from app import database
        conn = Connection()
        catalog = Catalog(items=[item(n) for n in range(12)])
        with patch.object(database, "get_pool", return_value=Pool(conn)), patch.object(store, "safe_catalog", return_value=catalog), patch.object(store, "now_kst", return_value=NOW):
            await service.browse_response("주변맛집 궁동 1만원 미만", "test-user-a")
            await service.browse_response(service.HOME, "test-user-b")
            responses = await asyncio.gather(service.browse_response(service.MORE, "test-user-a"), service.browse_response(service.MORE, "test-user-a"))
        self.assertFalse({c["title"] for c in cards(responses[0])} & {c["title"] for c in cards(responses[1])})
        self.assertEqual(len(conn.states), 2)
        self.assertTrue(all(len(key) == 64 and "test-user" not in key for key in conn.states))
        self.assertNotIn("test-user", json.dumps(conn.states))

    async def test_analytics_failure_does_not_disable_browsing(self):
        from app import database
        conn = Connection(); conn.fail_events = True
        with patch.object(database, "get_pool", return_value=Pool(conn)), patch.object(store, "safe_catalog", return_value=Catalog(items=[item()])), patch.object(store, "now_kst", return_value=NOW):
            response = await service.browse_response("주변맛집 궁동 1만원 미만", "test-user")
        self.assertIn(service.MORE, messages(response))
        self.assertEqual(len(conn.states), 1)

    async def test_db_failure_returns_basic_recommendation_without_state_controls(self):
        from app import database
        with patch.object(database, "get_pool", side_effect=RuntimeError), patch.object(store, "safe_catalog", return_value=Catalog(items=[item()])), patch.object(store, "now_kst", return_value=NOW):
            response = await service.browse_response("주변맛집 궁동 1만원 미만", "test-user")
        self.assertEqual(len(cards(response)), 1)
        self.assertNotIn(service.MORE, messages(response))
        self.assertNotIn(service.RATING_MENU, messages(response))


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        env = patch.dict(os.environ, {"RESTAURANTS_DATA_PATH": str(Path(self.folder.name) / "catalog.json"),
            "ADMIN_USERNAME": "test-admin", "ADMIN_PASSWORD": "test-password",
            "RESTAURANTS_TRACKING_SECRET": "test-only-secret", "SERVER_URL": "https://example.com"})
        env.start(); self.addCleanup(env.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.auth = ("test-admin", "test-password")
        self.headers = {"X-Restaurants-Editor": "1"}

    def test_admin_auth_csrf_durable_save_conflict_preview_and_empty_default(self):
        endpoint = "/admin/restaurants/catalog"
        self.assertEqual(self.client.get(endpoint).status_code, 401)
        initial = self.client.get(endpoint, auth=self.auth).json()
        self.assertEqual(initial["items"], [])
        self.assertEqual(self.client.put(endpoint, auth=self.auth, json=initial).status_code, 403)
        catalog = Catalog(items=[item()]).model_dump(mode="json")
        saved = self.client.put(endpoint, auth=self.auth, headers=self.headers, json=catalog)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["revision"], 1)
        self.assertEqual(self.client.put(endpoint, auth=self.auth, headers=self.headers, json=catalog).status_code, 409)
        self.assertEqual(self.client.get(endpoint, auth=self.auth).json(), saved.json())
        before = store.catalog_path().read_bytes()
        preview = self.client.post("/admin/restaurants/preview", auth=self.auth, headers=self.headers, json=saved.json())
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(len(preview.json()["previews"]), 9)
        self.assertEqual(before, store.catalog_path().read_bytes())
        self.assertEqual(self.client.get("/admin/restaurants", auth=self.auth).status_code, 200)

    def test_all_post_routes_accept_kakao_request_and_enforce_endpoint_message_mapping(self):
        with patch.object(service, "browse_response", return_value=service.home_response()) as browse:
            for route, utterances in service.ROUTE_MESSAGES.items():
                for utterance in utterances:
                    response = self.client.post("/restaurants/" + route, json={"userRequest": {"utterance": utterance, "user": {"id": "test-user"}}})
                    self.assertEqual(response.status_code, 200)
                    browse.assert_awaited_with(utterance, "test-user")
            before = browse.await_count
            self.client.post("/restaurants/home", json={"userRequest": {"utterance": "주변맛집 궁동 1만원 미만"}})
            self.assertEqual(browse.await_count, before)
        self.assertEqual(self.client.post("/restaurants/home", json={}).status_code, 422)

    def test_signed_redirect_rejects_tamper_expiry_and_arbitrary_url_and_click_deduplicates(self):
        from app import database
        conn = Connection()
        catalog = store.save_catalog(Catalog(items=[item()]))
        clock = store.now_kst()
        state, _, _ = service.transition(None, "주변맛집 궁동 1만원 미만", catalog, "hash", clock)
        url = service.map_link(catalog.items[0], state, "hash", clock)
        token = parse_qs(urlsplit(url).query)["token"][0]
        self.assertIsNone(service.read_map_token(token + "x", clock))
        self.assertIsNone(service.read_map_token(token, clock + timedelta(days=7)))
        self.assertEqual(self.client.get("/restaurants/map?token=invalid", follow_redirects=False).status_code, 400)
        with patch.object(database, "get_pool", return_value=Pool(conn)):
            for _ in range(2):
                response = self.client.get(urlsplit(url).path + "?" + urlsplit(url).query, follow_redirects=False)
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.headers["location"], "https://place.map.kakao.com/1")
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(len(conn.events), 1)
        store.save_catalog(catalog.model_copy(update={"items": []}))
        self.assertEqual(self.client.get("/restaurants/map?token=" + token, follow_redirects=False).status_code, 404)

    def test_api_error_never_exposes_authentication_or_raw_exception(self):
        with patch.object(store, "search_places", side_effect=RuntimeError("private-test-value")):
            response = self.client.post("/admin/restaurants/search", auth=self.auth, headers=self.headers, json={"query": "궁동 밥집"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("private-test-value", response.text)


if __name__ == "__main__":
    unittest.main()
