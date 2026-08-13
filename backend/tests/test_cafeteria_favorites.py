import unittest

from app.services import cafeteria, cafeteria_favorites


class CafeteriaFavoritesTest(unittest.TestCase):
    def test_parse_favorite_place_from_message(self):
        self.assertEqual(
            cafeteria_favorites.parse_favorite_place("기숙사 즐겨찾기"),
            "dorm",
        )
        self.assertEqual(
            cafeteria_favorites.parse_favorite_place("3학생회관 즐겨찾기 해제"),
            "hall_3",
        )
        self.assertEqual(
            cafeteria_favorites.parse_favorite_place("제3학생회관 즐겨찾기 해제"),
            "hall_3",
        )
        self.assertEqual(
            cafeteria_favorites.parse_favorite_place("생활과학대학 즐겨찾기"),
            "life_science",
        )

    def test_empty_favorites_response_has_total_schedule_cta(self):
        response = cafeteria_favorites.create_empty_favorites_response()
        card = response["template"]["outputs"][0]["textCard"]

        self.assertEqual(card["title"], "즐겨찾기한 식당이 없어요")
        self.assertEqual(card["buttons"][0]["messageText"], "학식")

    def test_toggle_response_uses_korean_object_particle(self):
        dorm_result = cafeteria_favorites.FavoriteToggleResult(
            place="dorm",
            place_name="기숙사",
            added=True,
            remaining_count=1,
        )
        hall_result = cafeteria_favorites.FavoriteToggleResult(
            place="hall_3",
            place_name="3학생회관",
            added=False,
            remaining_count=0,
        )

        dorm_card = cafeteria_favorites.create_toggle_response(dorm_result)[
            "template"
        ]["outputs"][0]["textCard"]
        hall_card = cafeteria_favorites.create_toggle_response(hall_result)[
            "template"
        ]["outputs"][0]["textCard"]

        self.assertEqual(dorm_card["title"], "기숙사를 즐겨찾기에 추가했어요")
        self.assertEqual(hall_card["title"], "3학생회관을 즐겨찾기에서 해제했어요")

    def test_dorm_schedule_has_crowding_button_after_favorite_button(self):
        schedule_data = [
            {
                "place": "dorm",
                "date": "08/11 ~ 08/15",
                "extra": "",
                "hours": {
                    "breakfast": {"open": "08:00", "close": "09:00"},
                    "lunch": {"open": "11:30", "close": "13:00"},
                    "dinner": {"open": "17:30", "close": "19:00"},
                },
            }
        ]

        response = cafeteria.create_schedule_response(schedule_data, {"dorm"})
        card = response["template"]["outputs"][0]["carousel"]["items"][0]
        buttons = card["buttons"]

        self.assertEqual([button["label"] for button in buttons], [
            "식단 보기",
            "★ 해제하기",
            "혼잡도 보기",
        ])
        self.assertEqual(buttons[2]["messageText"], "기숙사 혼잡도")
        self.assertEqual(card["buttonLayout"], "vertical")

    def test_dorm_crowding_response_visualizes_current_and_recent_trend(self):
        response = cafeteria.create_dorm_crowding_response(
            {
                "current": 160,
                "available": 160,
                "capacity": 320,
                "chart": [0, 20, 40, 80, 120, 160, 120, 80, 40],
            }
        )
        card = response["template"]["outputs"][0]["textCard"]

        self.assertIn("혼잡률: █████░░░░░ 50%", card["description"])
        self.assertIn("최근 추이(40분 전 → 현재)", card["description"])
        self.assertIn("▁", card["description"])
        self.assertIn("█", card["description"])
        self.assertIn("0명 → 40명", card["description"])


if __name__ == "__main__":
    unittest.main()
