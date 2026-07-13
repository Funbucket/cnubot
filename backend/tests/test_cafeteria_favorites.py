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


if __name__ == "__main__":
    unittest.main()
