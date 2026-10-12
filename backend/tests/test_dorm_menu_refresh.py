import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from app.routers import cafeteria
from app.schemas.kakao_request import KakaoRequest
from app.services.dorm_menu import DormMenuUnavailable, ensure_current_menu, read_current_menu
from tests.test_dorm_scraper import week_menu


TODAY = date(2026, 10, 12)


class DormMenuRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.path = self.directory / "dorm_menu.json"

    @mock.patch("app.services.dorm_menu.scrape_current_week_dorm_menu")
    def test_valid_week_is_read_without_network(self, scrape):
        self.path.write_text(json.dumps(week_menu(TODAY)))
        ensure_current_menu(self.directory, TODAY)
        scrape.assert_not_called()

    @mock.patch("app.services.dorm_menu.scrape_current_week_dorm_menu")
    def test_recovers_missing_corrupt_incomplete_and_previous_week(self, scrape):
        incomplete = week_menu(TODAY)
        incomplete["menu"].pop()
        for saved in (None, "{broken", json.dumps(incomplete),
                      json.dumps(week_menu(date(2026, 10, 5)))):
            if saved is None:
                self.path.unlink(missing_ok=True)
            else:
                self.path.write_text(saved)
            scrape.return_value = week_menu(TODAY)
            with self.subTest(saved=saved):
                ensure_current_menu(self.directory, TODAY)
                self.assertEqual(read_current_menu(self.directory, TODAY)["date"], "10/12 ~ 10/18")
        self.assertEqual(scrape.call_count, 4)

    @mock.patch("app.services.dorm_menu.scrape_current_week_dorm_menu")
    def test_failed_recovery_preserves_file_and_can_retry(self, scrape):
        old = json.dumps(week_menu(date(2026, 10, 5)))
        self.path.write_text(old)
        scrape.side_effect = [ValueError("not published"), week_menu(TODAY)]
        with self.assertRaises(ValueError):
            ensure_current_menu(self.directory, TODAY)
        self.assertEqual(self.path.read_text(), old)
        with self.assertRaises(DormMenuUnavailable):
            read_current_menu(self.directory, TODAY)
        self.assertEqual(ensure_current_menu(self.directory, TODAY)["date"], "10/12 ~ 10/18")

    @mock.patch("app.services.dorm_menu.scrape_current_week_dorm_menu")
    def test_invalid_download_does_not_overwrite_existing_file(self, scrape):
        saved = json.dumps(week_menu(TODAY))
        self.path.write_text(saved)
        scrape.return_value = week_menu(date(2026, 10, 19))
        with self.assertRaises(DormMenuUnavailable):
            ensure_current_menu(self.directory, TODAY, force=True)
        self.assertEqual(self.path.read_text(), saved)


class DormMenuResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_both_routes_refuse_stale_menu_and_keep_registered_buttons(self):
        for utterance, route in (("월요일기숙사", cafeteria.get_menu_by_day),
                                 ("기숙사", cafeteria.get_today_menu)):
            req = KakaoRequest(userRequest={"utterance": utterance})
            with mock.patch.object(cafeteria.common, "load_data", mock.AsyncMock(
                return_value=week_menu(date(2026, 10, 5))
            )), mock.patch.object(cafeteria.common, "get_current_kr_time",
                                 return_value=datetime(2026, 10, 12, 10)), \
                 mock.patch.object(cafeteria, "_menu_response", mock.AsyncMock()) as build:
                response = json.loads((await route(req)).body)
            build.assert_not_called()
            self.assertIn("이번 주 기숙사 식단", response["template"]["outputs"][0]["simpleText"]["text"])
            self.assertEqual([x["messageText"] for x in response["template"]["quickReplies"]],
                             [f"{day}요일기숙사" for day in "월화수목금토일"])

    async def test_current_week_reaches_normal_menu_response(self):
        req = KakaoRequest(userRequest={"utterance": "월요일기숙사"})
        with mock.patch.object(cafeteria.common, "load_data", mock.AsyncMock(return_value=week_menu(TODAY))), \
             mock.patch.object(cafeteria.common, "get_current_kr_time", return_value=datetime(2026, 10, 12)), \
             mock.patch.object(cafeteria, "_menu_response", mock.AsyncMock(return_value={"version": "2.0"})) as build:
            await cafeteria.get_menu_by_day(req)
        build.assert_awaited_once()

    async def test_schedule_hides_stale_operating_date(self):
        with mock.patch.object(cafeteria.common, "load_data", mock.AsyncMock(
            return_value=week_menu(date(2026, 10, 5))
        )), mock.patch.object(cafeteria.common, "get_current_kr_time", return_value=datetime(2026, 10, 12)):
            self.assertEqual(await cafeteria.common.get_operating_date_for_place("dorm"), "")
