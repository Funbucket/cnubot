import unittest

from app.services import restaurants


class RestaurantsTest(unittest.TestCase):
    def test_parse_area_from_utterance(self):
        self.assertEqual(restaurants.parse_area("정문 근처 맛집"), "front_gate")
        self.assertEqual(restaurants.parse_area("교내 맛집"), "main")
        self.assertEqual(restaurants.parse_area("주변 맛집"), "dorm")

    def test_normalize_kakao_place(self):
        place = restaurants._normalize_place(
            {
                "id": "1",
                "place_name": "충대분식",
                "category_name": "음식점 > 분식",
                "road_address_name": "대전 유성구 대학로 99",
                "address_name": "대전 유성구 궁동 220",
                "phone": "042-000-0000",
                "place_url": "https://place.map.kakao.com/1",
                "distance": "123",
            }
        )

        self.assertEqual(place["name"], "충대분식")
        self.assertEqual(place["category"], "음식점 > 분식")
        self.assertEqual(place["address"], "대전 유성구 대학로 99")
        self.assertEqual(place["distance"], 123)

    def test_nearby_restaurants_response_uses_carousel_and_price_quick_replies(self):
        response = restaurants.create_nearby_restaurants_response(
            "dorm",
            [
                {
                    "id": "1",
                    "name": "충대분식",
                    "category": "음식점 > 분식",
                    "address": "대전 유성구 대학로 99",
                    "phone": "",
                    "url": "https://place.map.kakao.com/1",
                    "distance": 123,
                    "min_price": 6500,
                    "representative_menus": [
                        {"name": "김치찌개", "price": 6500},
                        {"name": "제육덮밥", "price": 8000},
                    ],
                }
            ],
        )

        item = response["template"]["outputs"][0]["carousel"]["items"][0]
        quick_replies = response["template"]["quickReplies"]

        self.assertEqual(item["title"], "충대분식")
        self.assertIn("최저가: 6,500원", item["description"])
        self.assertIn("김치찌개 6,500원", item["description"])
        self.assertIn("거리: 약 123m", item["description"])
        self.assertEqual(item["buttons"][0]["label"], "지도 보기")
        self.assertEqual(
            [reply["label"] for reply in quick_replies],
            ["7천원 이하", "1만원 이하", "1.5만원 이하"],
        )

    def test_kakao_config_required_response(self):
        response = restaurants.create_kakao_config_required_response()
        card = response["template"]["outputs"][0]["textCard"]

        self.assertEqual(card["title"], "카카오 로컬 API 설정이 필요해요")

    def test_kakao_api_unavailable_response(self):
        response = restaurants.create_kakao_api_unavailable_response()
        card = response["template"]["outputs"][0]["textCard"]

        self.assertEqual(card["title"], "카카오 로컬 API를 사용할 수 없어요")

    def test_extract_menu_items_uses_store_menu_prices(self):
        payload = {
            "menu": {
                "menus": {
                    "items": [
                        {"name": "돈코츠라멘", "price": 7900, "mod_at": "2026-01-01"},
                        {"name": "가격없음", "price": 0},
                    ],
                    "items_updated_at": "2026-01-01 12:00:00",
                },
                "yogiyo_menus": {
                    "items": [{"name": "돈코츠라멘", "price": 10500}],
                },
            }
        }

        menus = restaurants._extract_menu_items(payload)

        self.assertEqual(menus, [
            {
                "name": "돈코츠라멘",
                "price": 7900,
                "description": "",
                "updated_at": "2026-01-01",
            }
        ])
        self.assertEqual(
            restaurants._extract_menu_updated_at(payload),
            "2026-01-01 12:00:00",
        )

    def test_create_menu_summary_from_payload(self):
        payload = {
            "menu": {
                "menus": {
                    "items": [
                        {"name": "마제소바", "price": 8900},
                        {"name": "돈코츠라멘", "price": 7900},
                    ],
                    "items_updated_at": "2026-01-01 12:00:00",
                }
            }
        }

        menus = restaurants._extract_menu_items(payload)
        prices = [menu["price"] for menu in menus]

        self.assertEqual(min(prices), 7900)
        self.assertEqual(menus[0]["name"], "마제소바")


if __name__ == "__main__":
    unittest.main()
