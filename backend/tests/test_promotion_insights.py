"""Opt-in PostgreSQL checks using session-local temporary tables only."""
import os
import unittest
from datetime import date
from unittest.mock import patch

import asyncpg
from app.services import experiments


@unittest.skipUnless(os.getenv("RUN_PROMOTION_DB_TESTS") == "1", "opt-in PostgreSQL test")
class PromotionInsightsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        await self.conn.execute("""
            SET TIME ZONE 'UTC';
            CREATE TEMP TABLE user_events (
                user_id TEXT, event_name TEXT, created_at TIMESTAMPTZ,
                properties JSONB DEFAULT '{}', source TEXT, product_key TEXT,
                experiment_id BIGINT, variant_key TEXT
            );
            CREATE TEMP VIEW qualified_promotion_events AS SELECT * FROM pg_temp.user_events;
        """)
        conn = self.conn

        class Acquire:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *args):
                pass

        class Pool:
            def acquire(self):
                return Acquire()

        self.pool_patch = patch.object(experiments, "get_pool", return_value=Pool())
        self.pool_patch.start()

    async def asyncTearDown(self):
        self.pool_patch.stop()
        await self.conn.close()  # Temporary tables are destroyed with this connection.

    async def event(self, user, name, timestamp):
        await self.conn.execute("INSERT INTO pg_temp.user_events(user_id,event_name,created_at) VALUES($1,$2,$3::text::timestamptz)", user, name, timestamp)

    async def test_later_valid_click_counts_and_funnel_is_monotonic(self):
        await self.event("repeat", "promotion_entry_click", "2026-09-10 09:00+09")
        await self.event("repeat", "promotion_entry_exposure", "2026-09-10 10:00+09")
        await self.event("repeat", "promotion_entry_click", "2026-09-10 10:01+09")
        await self.event("repeat", "promotion_exposure", "2026-09-10 10:02+09")
        await self.event("repeat", "commerce_card_click", "2026-09-10 10:03+09")
        await self.event("invalid", "promotion_entry_click", "2026-09-10 09:00+09")
        await self.event("invalid", "promotion_entry_exposure", "2026-09-10 10:00+09")
        await self.event("invalid", "promotion_exposure", "2026-09-10 10:02+09")
        data = await experiments.get_promotion_insights(date(2026,9,10), date(2026,9,10))
        totals = data["totals"]
        self.assertEqual([totals[key] for key in ("entry_exposed_users", "entry_users", "exposed_users", "clicked_users")], [2,1,1,1])

    async def test_korean_day_boundaries_independent_of_database_timezone(self):
        await self.event("before", "promotion_entry_exposure", "2026-09-09 23:59:59+09")
        await self.event("first", "promotion_entry_exposure", "2026-09-10 00:00:00+09")
        await self.event("last", "promotion_entry_exposure", "2026-09-10 23:59:59+09")
        await self.event("after", "promotion_entry_exposure", "2026-09-11 00:00:00+09")
        data = await experiments.get_promotion_insights(date(2026,9,10), date(2026,9,10))
        self.assertEqual(data["totals"]["entry_exposed_users"], 2)
        self.assertEqual([row["day"] for row in data["daily"]], [date(2026,9,10)])


class PathSummaryTest(unittest.TestCase):
    def _row(self, **overrides):
        row = {
            "path": "entry", "entry_exposed_users": 1000, "entry_exposure_events": 2400,
            "entry_users": 50, "exposed_users": 50, "exposure_events": 300,
            "clicked_users": 5, "click_events": 6,
        }
        row.update(overrides)
        return row

    def test_entry_path_reach_is_the_button_impression(self):
        summary = experiments._summarize_paths([self._row()])[0]

        self.assertEqual(summary["reach_users"], 1000)
        self.assertEqual(summary["reach_events"], 2400)
        self.assertEqual(summary["action_users"], 50)
        self.assertAlmostEqual(summary["action_rate"], 5.0)
        self.assertAlmostEqual(summary["click_rate"], 0.5)
        self.assertAlmostEqual(summary["impressions_per_user"], 2.4)
        self.assertEqual(summary["steps"], 4)

    def test_inline_path_reach_is_the_card_itself(self):
        summary = experiments._summarize_paths([self._row(
            path="inline", entry_exposed_users=0, entry_exposure_events=0, entry_users=0,
            exposed_users=900, exposure_events=900, clicked_users=9, click_events=9,
        )])[0]

        # 진입 클릭 단계가 없으므로 반응이 곧 상품 클릭이다.
        self.assertEqual(summary["reach_users"], 900)
        self.assertEqual(summary["action_users"], summary["clicked_users"])
        self.assertAlmostEqual(summary["click_rate"], 1.0)
        self.assertEqual(summary["steps"], 2)

    def test_paths_are_ordered_by_reach_and_survive_empty_data(self):
        summaries = experiments._summarize_paths([
            self._row(entry_exposed_users=10, entry_exposure_events=10),
            self._row(path="inline", exposed_users=800, exposure_events=800),
        ])

        self.assertEqual([item["path"] for item in summaries], ["inline", "entry"])
        empty = experiments._summarize_paths([self._row(
            entry_exposed_users=0, entry_exposure_events=0, entry_users=0, clicked_users=0,
        )])[0]
        self.assertEqual(empty["action_rate"], 0)
        self.assertEqual(empty["impressions_per_user"], 0)


class GuardrailSummaryTest(unittest.TestCase):
    def _row(self, day, active, returned, views=0, view_users=0):
        return {
            "day": date(2026, 9, day), "active_users": active, "returned_users": returned,
            "menu_views": views, "menu_view_users": view_users,
        }

    def test_computes_return_rate_and_views_per_user(self):
        rows = [self._row(10, 100, 0), self._row(9, 200, 80, views=500, view_users=200)]

        summaries = {item["day"].day: item for item in experiments._summarize_guardrails(rows, today=date(2026, 9, 11))}

        self.assertAlmostEqual(summaries[9]["return_rate"], 40.0)
        self.assertAlmostEqual(summaries[9]["views_per_user"], 2.5)
        self.assertTrue(summaries[9]["return_rate_measurable"])

    def test_a_day_whose_successor_is_still_running_stays_pending(self):
        # 오늘이 9/11이면 9/10의 재방문율은 아직 하루가 끝나지 않아 낮게 나온다.
        rows = [self._row(10, 100, 2), self._row(9, 200, 80)]

        summaries = {item["day"].day: item for item in experiments._summarize_guardrails(rows, today=date(2026, 9, 11))}

        self.assertTrue(summaries[10]["return_rate_pending"])
        self.assertFalse(summaries[10]["return_rate_measurable"])
        self.assertFalse(summaries[9]["return_rate_pending"])

    def test_a_collection_gap_is_not_reported_as_zero_retention(self):
        # 9/8 데이터가 통째로 없으면 9/7 재방문율은 0%가 아니라 측정 불가다.
        rows = [self._row(10, 100, 0), self._row(9, 200, 80), self._row(7, 1200, 0)]

        summaries = {item["day"].day: item for item in experiments._summarize_guardrails(rows, today=date(2026, 9, 11))}

        self.assertFalse(summaries[7]["return_rate_measurable"])
        self.assertFalse(summaries[7]["return_rate_pending"])

    def test_days_without_menu_view_instrumentation_report_no_views(self):
        summaries = experiments._summarize_guardrails([self._row(9, 200, 80)], today=date(2026, 9, 11))

        self.assertEqual(summaries[0]["views_per_user"], 0)
