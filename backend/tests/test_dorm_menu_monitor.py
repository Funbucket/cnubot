import unittest
from datetime import datetime, timezone
from unittest import mock
from zoneinfo import ZoneInfo

from app.jobs.monitor_dorm_menu import check_current_menu, in_check_window


KST = ZoneInfo("Asia/Seoul")


class DormMenuMonitorScheduleTest(unittest.TestCase):
    def test_sunday_evening_through_monday_morning_only(self):
        cases = [
            (datetime(2026, 10, 11, 18, 59, tzinfo=KST), False),
            (datetime(2026, 10, 11, 19, 0, tzinfo=KST), True),
            (datetime(2026, 10, 11, 23, 45, tzinfo=KST), True),
            (datetime(2026, 10, 12, 0, 0, tzinfo=KST), True),
            (datetime(2026, 10, 12, 8, 45, tzinfo=KST), True),
            (datetime(2026, 10, 12, 9, 0, 2, tzinfo=KST), True),
            (datetime(2026, 10, 12, 9, 1, tzinfo=KST), False),
            (datetime(2026, 10, 13, 7, 0, tzinfo=KST), False),
            (datetime(2026, 10, 17, 20, 0, tzinfo=KST), False),
        ]
        for now, expected in cases:
            with self.subTest(now=now):
                self.assertEqual(in_check_window(now), expected)
                self.assertEqual(in_check_window(now.astimezone(timezone.utc)), expected)

    @mock.patch("app.jobs.monitor_dorm_menu.ensure_current_menu")
    def test_outside_window_skips_file_checks_and_collection(self, ensure):
        self.assertIsNone(check_current_menu(datetime(2026, 10, 12, 10, 0, tzinfo=KST)))
        ensure.assert_not_called()

    @mock.patch("app.jobs.monitor_dorm_menu.ensure_current_menu")
    def test_monday_check_uses_new_week_date(self, ensure):
        now = datetime(2026, 10, 12, 0, 0, tzinfo=KST)
        self.assertEqual(check_current_menu(now), ensure.return_value)
        ensure.assert_called_once_with(today=now.date())
