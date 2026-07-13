import unittest

from app.services import cafeteria_favorites


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


if __name__ == "__main__":
    unittest.main()
