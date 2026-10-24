"""Financial totals must be complete, scoped by payment dates, and never fabricated."""
import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import insights_api
from app.services import toss_revenue as revenue


def response(amount=100, updated="2026-10-18T10:00:00"):
    summary = dict.fromkeys(revenue.FIELDS, 0)
    summary.update(expectedCommissionAmount=amount * 2, confirmedCommissionAmount=amount,
                   netPaymentAmount=amount * 10, clickCount=3, soldQuantity=2,
                   refundedQuantity=1, lastUpdatedAt=updated)
    return {"resultType": "SUCCESS", "success": {
        "summary": summary, "hasNext": True, "nextCursor": "another-page",
        "items": [{"confirmedCommissionAmount": amount}],
    }}


class RevenueTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        revenue._cache.clear()
        env = patch.dict(os.environ, {"TOSS_ACCESS_KEY": "test", "TOSS_SECRET_KEY": "test"})
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(revenue._cache.clear)

    async def test_split_range_sums_each_full_summary_once_without_pagination(self):
        with patch.object(revenue.toss, "_get_live_sync", side_effect=[response(100), response(250)]) as fetch:
            report = await revenue.get_revenue(date(2026, 9, 1), date(2026, 10, 2))
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["summary"]["confirmedCommissionAmount"], 350)
            self.assertEqual(report["summary"]["expectedCommissionAmount"], 700)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(fetch.call_args_list[0].args[1], {
                "fromDate": "2026-09-01", "toDate": "2026-10-01", "size": 1,
            })
            self.assertEqual(fetch.call_args_list[1].args[1]["fromDate"], "2026-10-02")

    async def test_long_range_and_cache_preserve_nonoverlapping_windows(self):
        with patch.object(revenue.toss, "_get_live_sync", return_value=response()) as fetch:
            report = await revenue.get_revenue(date(2026, 8, 31), date(2026, 10, 1))
            again = await revenue.get_revenue(date(2026, 8, 31), date(2026, 10, 1))
        self.assertEqual(report["summary"]["confirmedCommissionAmount"], 200)
        self.assertEqual(report["fetched_at"], again["fetched_at"])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual([call.args[1]["fromDate"] for call in fetch.call_args_list],
                         ["2026-08-31", "2026-10-01"])
        self.assertEqual([call.args[1]["toDate"] for call in fetch.call_args_list],
                         ["2026-09-30", "2026-10-01"])

    async def test_failed_second_window_never_displays_partial_totals(self):
        with patch.object(revenue.toss, "_get_live_sync", side_effect=[response(), requests.Timeout()]):
            report = await revenue.get_revenue(date(2026, 8, 31), date(2026, 10, 1))
        self.assertEqual(report, {"status": "unavailable"})

    async def test_zero_sales_keeps_toss_visits_and_null_update(self):
        body = response(0, None)
        body["success"]["items"] = []
        body["success"]["summary"].update(soldQuantity=0, refundedQuantity=0)
        with patch.object(revenue.toss, "_get_live_sync", return_value=body):
            report = await revenue.get_revenue(date(2026, 10, 1), date(2026, 10, 1))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["summary"]["clickCount"], 3)
        self.assertIsNone(report["last_updated_at"])

    async def test_missing_or_malformed_financial_data_is_unavailable(self):
        null_amount, missing_amount, string_amount = response(), response(), response()
        null_amount["success"]["summary"]["confirmedCommissionAmount"] = None
        del missing_amount["success"]["summary"]["confirmedCommissionAmount"]
        string_amount["success"]["summary"]["confirmedCommissionAmount"] = "100"
        for body in [{"resultType": "FAIL"}, {"resultType": "SUCCESS", "success": {}},
                     null_amount, missing_amount, string_amount]:
            with self.subTest(body=body), patch.object(revenue.toss, "_get_live_sync", return_value=body):
                report = await revenue.get_revenue(date(2026, 10, 1), date(2026, 10, 1))
                self.assertEqual(report, {"status": "unavailable"})

    async def test_expired_token_is_refreshed_once(self):
        with patch.object(revenue.toss, "_get_live_sync", side_effect=[
            revenue.toss.TossSharelinkError("Toss HTTP 401"), response(),
        ]) as fetch, patch.object(revenue.toss, "_token", ("expired", 0)):
            report = await revenue.get_revenue(date(2026, 10, 1), date(2026, 10, 1))
            self.assertEqual(report["status"], "ok")
            self.assertEqual(fetch.call_count, 2)
            self.assertIsNone(revenue.toss._token)

    async def test_missing_configuration_does_not_call_toss(self):
        with patch.dict(os.environ, {"TOSS_ACCESS_KEY": ""}), \
             patch.object(revenue.toss, "_get_live_sync") as fetch:
            self.assertEqual(await revenue.get_revenue(), {"status": "not_configured"})
            fetch.assert_not_called()

    async def test_all_time_uses_first_promotion_date_and_today_kst(self):
        conn = AsyncMock()
        conn.fetchval.return_value = date(2026, 9, 3)
        pool = unittest.mock.MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        with patch("app.database.get_pool", return_value=pool), \
             patch.object(revenue.toss, "_get_live_sync", return_value=response()) as fetch:
            report = await revenue.get_revenue()
        self.assertEqual(report["start_date"], date(2026, 9, 3))
        self.assertEqual(report["end_date"], datetime.now(revenue.KST).date())
        self.assertEqual(fetch.call_args_list[0].args[1]["fromDate"], "2026-09-03")

    def test_windows_cover_leap_day_and_inclusive_boundaries(self):
        self.assertEqual(list(revenue.date_windows(date(2024, 2, 1), date(2024, 3, 3))), [
            (date(2024, 2, 1), date(2024, 3, 2)), (date(2024, 3, 3), date(2024, 3, 3)),
        ])


class RevenueRouteTest(unittest.TestCase):
    def setUp(self):
        app = FastAPI()
        app.include_router(insights_api.router, prefix="/admin")
        self.client = TestClient(app)
        self.env = patch.dict(os.environ, {"ADMIN_USERNAME": "test", "ADMIN_PASSWORD": "test"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_requires_authentication_before_querying_revenue(self):
        with patch.object(revenue, "get_revenue", AsyncMock()) as fetch:
            result = self.client.get("/admin/insights/api/revenue")
        self.assertEqual(result.status_code, 401)
        fetch.assert_not_called()

    def test_uses_selected_dates_and_returns_uncacheable_json(self):
        with patch.object(revenue, "get_revenue", AsyncMock(return_value={"status": "unavailable"})) as fetch:
            result = self.client.get("/admin/insights/api/revenue?start_date=2026-09-01&end_date=2026-10-01", auth=("test", "test"))
        fetch.assert_awaited_once_with(date(2026, 9, 1), date(2026, 10, 1))
        self.assertEqual(result.status_code, 200)
        self.assertIn("no-store", result.headers["Cache-Control"])
        self.assertEqual(result.json()["data"], {"status": "unavailable"})

    def test_invalid_range_never_calls_toss(self):
        with patch.object(revenue, "get_revenue", AsyncMock()) as fetch:
            result = self.client.get("/admin/insights/api/revenue?start_date=2026-10-02&end_date=2026-10-01", auth=("test", "test"))
        self.assertEqual(result.status_code, 400)
        fetch.assert_not_called()

    def test_default_week_and_all_time_match_insights_filters(self):
        with patch.object(revenue, "get_revenue", AsyncMock(return_value={"status": "unavailable"})) as fetch:
            self.client.get("/admin/insights/api/revenue", auth=("test", "test"))
            today = datetime.now(revenue.KST).date()
            fetch.assert_awaited_with(today - timedelta(days=6), today)
            self.client.get("/admin/insights/api/revenue?all_time=true", auth=("test", "test"))
            fetch.assert_awaited_with(None, None)

    def test_json_totals_separate_confirmed_expected_and_sales(self):
        data = {"status": "ok", "summary": response(1234)["success"]["summary"]}
        with patch.object(revenue, "get_revenue", AsyncMock(return_value=data)):
            result = self.client.get("/admin/insights/api/revenue", auth=("test", "test"))
        summary = result.json()["data"]["summary"]
        self.assertEqual(summary["confirmedCommissionAmount"], 1234)
        self.assertEqual(summary["expectedCommissionAmount"], 2468)
        self.assertEqual(summary["netPaymentAmount"], 12340)
