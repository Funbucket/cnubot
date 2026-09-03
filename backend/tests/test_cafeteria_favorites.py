import unittest

from app.services import cafeteria


class CafeteriaScheduleTest(unittest.TestCase):
    def test_dorm_schedule_has_crowding_button(self):
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

        response = cafeteria.create_schedule_response(schedule_data)
        card = response["template"]["outputs"][0]["carousel"]["items"][0]
        buttons = card["buttons"]

        self.assertEqual([button["label"] for button in buttons], ["식단 보기", "혼잡도 보기"])
        self.assertEqual(buttons[1]["messageText"], "기숙사 혼잡도")

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
