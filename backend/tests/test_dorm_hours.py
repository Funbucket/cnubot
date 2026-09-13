import asyncio
import unittest
from datetime import datetime
from unittest import mock

from app.routers import cafeteria as cafeteria_router
from app.scrapers.dorm import scrape_dorm_hours
from app.services import cafeteria, promotions


HOURS_HTML = """
<ul class="mealPlan-wrap">
  <li><strong class="tit">아침</strong><div class="mw-inner">
      <span class="txt">07:30~09:00</span>
      <p class="txt-check">토/일요일 및 공휴일 07:30~09:00</p></div></li>
  <li><strong class="tit">점심</strong><div class="mw-inner">
      <span class="txt">11:30~13:30</span></div></li>
  <li><strong class="tit">저녁</strong><div class="mw-inner">
      <span class="txt">17:00~19:30</span>
      <p class="txt-check">방학기간은 17:00~19:30</p>
      <p class="txt-check">토/일요일 및 공휴일 17:30~19:00</p></div></li>
</ul>
"""

MENU_DATA = {
    "breakfast": [{"type": "메인A", "menu": ["누룽지", "계란국"]}],
    "lunch": [{"type": "메인A", "menu": ["제육김치덮밥"], "price": 6000}],
    "dinner": [{"type": "메인A", "menu": ["잡곡밥"]}],
}

INLINE_PRODUCT = {
    "title": "리벤스 라벤더 물티슈",
    "price": 7500,
    "original_price": 29900,
    "discount_rate": 74,
    "image_url": "https://example.com/a.jpg",
    "url": "https://toss.im/_m/abc",
}


class DormHoursScraperTest(unittest.TestCase):
    def test_parses_each_meal_window_and_notes(self):
        response = mock.Mock(content=HOURS_HTML.encode())
        with mock.patch("app.scrapers.dorm.requests.get", return_value=response):
            hours = scrape_dorm_hours()["hours"]

        self.assertEqual(hours["breakfast"], {"open": "07:30", "close": "09:00"})
        self.assertEqual(hours["lunch"], {"open": "11:30", "close": "13:30"})
        self.assertEqual(hours["dinner"]["close"], "19:30")
        self.assertEqual(hours["dinner"]["extra"], "주말·공휴일 17:30~19:00")

    def test_drops_notes_that_only_repeat_the_main_window(self):
        response = mock.Mock(content=HOURS_HTML.encode())
        with mock.patch("app.scrapers.dorm.requests.get", return_value=response):
            hours = scrape_dorm_hours()["hours"]

        # 아침 안내와 저녁 방학 안내는 본 시간과 동일해서 카드 자리만 차지한다.
        self.assertNotIn("extra", hours["breakfast"])
        self.assertNotIn("방학", hours["dinner"].get("extra", ""))

    def test_shortens_verbose_notes(self):
        from app.scrapers.dorm import compact_hours_note

        self.assertEqual(
            compact_hours_note("  토/일요일 및 공휴일 17:30~19:00 "), "주말·공휴일 17:30~19:00"
        )
        self.assertEqual(compact_hours_note("방학기간은 18:00~19:30"), "방학 18:00~19:30")

    def test_raises_when_the_page_layout_changes(self):
        response = mock.Mock(content=b"<html><body>no hours here</body></html>")
        with mock.patch("app.scrapers.dorm.requests.get", return_value=response):
            with self.assertRaises(ValueError):
                scrape_dorm_hours()


class MealTimeOverTest(unittest.TestCase):
    HOURS = {"breakfast": {"open": "07:30", "close": "09:00"}}

    def test_before_and_after_closing(self):
        for hour, minute, expected in ((8, 59, False), (9, 0, False), (9, 1, True), (19, 0, True)):
            with self.subTest(time=f"{hour}:{minute}"):
                now = datetime(2026, 9, 10, hour, minute)
                self.assertIs(cafeteria.is_meal_time_over(self.HOURS, "breakfast", now), expected)

    def test_unknown_meal_is_never_over(self):
        now = datetime(2026, 9, 10, 23, 0)
        self.assertFalse(cafeteria.is_meal_time_over(self.HOURS, "dinner", now))
        self.assertFalse(cafeteria.is_meal_time_over({}, "breakfast", now))


class BreakfastReplacementTest(unittest.TestCase):
    def _inline(self):
        return {"inline_product_output": promotions.create_inline_product_output(INLINE_PRODUCT)}

    def _run(self, menu_data, over):
        with mock.patch.object(
            cafeteria, "dorm_meal_hours",
            new=mock.AsyncMock(return_value={"breakfast": {"close": "09:00"}}),
        ), mock.patch.object(cafeteria, "is_meal_time_over", return_value=over):
            return asyncio.run(
                cafeteria_router._replace_finished_breakfast(menu_data, self._inline(), "기숙사")
            )

    def test_finished_breakfast_is_replaced_and_restorable(self):
        menu_data, inline_product = self._run(MENU_DATA, over=True)

        self.assertEqual(menu_data["breakfast"], [])
        self.assertEqual(menu_data["lunch"], MENU_DATA["lunch"])
        buttons = inline_product["inline_product_output"]["commerceCard"]["buttons"]
        restore = buttons[-1]
        self.assertEqual(restore["label"], "아침 식단 보기")
        self.assertEqual(restore["messageText"], "기숙사")
        self.assertTrue(restore["extra"][cafeteria_router.SHOW_BREAKFAST_KEY])

    def test_breakfast_is_kept_while_it_is_still_served(self):
        menu_data, inline_product = self._run(MENU_DATA, over=False)

        self.assertEqual(menu_data["breakfast"], MENU_DATA["breakfast"])
        self.assertEqual(
            [button["label"] for button in inline_product["inline_product_output"]["commerceCard"]["buttons"]],
            ["구매하러 가기"],
        )

    def test_place_without_breakfast_is_untouched(self):
        menu_data, _ = self._run(dict(MENU_DATA, breakfast=[]), over=True)

        self.assertEqual(menu_data["breakfast"], [])


class RestoreRequestTest(unittest.TestCase):
    def _request(self, action):
        return mock.Mock(action=action)

    def test_reads_the_flag_from_either_extra_field(self):
        key = cafeteria_router.SHOW_BREAKFAST_KEY
        self.assertTrue(cafeteria_router._wants_breakfast(
            self._request(mock.Mock(clientExtra={key: True}, extra=None))))
        self.assertTrue(cafeteria_router._wants_breakfast(
            self._request(mock.Mock(clientExtra=None, extra={key: True}))))
        self.assertFalse(cafeteria_router._wants_breakfast(
            self._request(mock.Mock(clientExtra={}, extra=None))))
        self.assertFalse(cafeteria_router._wants_breakfast(self._request(None)))


if __name__ == "__main__":
    unittest.main()
