import unittest
from datetime import datetime
from unittest import mock

from app.routers import cafeteria as cafeteria_router
from app.services import cafeteria, promotions


MENU_DATA = {
    "breakfast": [{"type": "학생", "menu": ["누룽지", "계란국"], "price": 3000}],
    "lunch": [
        {"type": "학생", "menu": ["제육김치덮밥", "유부된장국", "생선까스"], "price": 6000},
        {"type": "직원", "menu": ["흑미밥", "두부된장국"], "price": 6000},
    ],
    "dinner": [{"type": "학생", "menu": ["잡곡밥", "탕수육"], "calorie": "841"}],
}

INLINE_PRODUCT = {
    "title": "리벤스 라벤더 물티슈, 100매, 10팩",
    "price": 7500,
    "original_price": 29900,
    "discount_rate": 74,
    "image_url": "https://example.com/a.jpg",
    "url": "https://toss.im/_m/abc",
}


class InlineQualityGateTest(unittest.TestCase):
    def _item(self, **overrides):
        item = {
            "displayName": "자취방 미니 가습기",
            "displayPrice": 12900,
            "discountRate": 45,
            "thumbnailUrl": "https://example.com/a.jpg",
        }
        item.update(overrides)
        return item

    def test_accepts_cheap_heavily_discounted_item(self):
        self.assertTrue(promotions.passes_inline_quality_gate(self._item()))

    def test_rejects_item_above_price_ceiling(self):
        self.assertFalse(promotions.passes_inline_quality_gate(self._item(displayPrice=25000)))

    def test_rejects_item_below_discount_floor(self):
        self.assertFalse(promotions.passes_inline_quality_gate(self._item(discountRate=10)))

    def test_rejects_sold_out_or_imageless_item(self):
        self.assertFalse(promotions.passes_inline_quality_gate(self._item(isSoldOut=True)))
        self.assertFalse(promotions.passes_inline_quality_gate(self._item(thumbnailUrl="")))

    def test_rejects_bulk_household_quantities(self):
        for title in (
            "스파클 종이컵, 185ml, 1000개, 1세트",
            "신선하랑 한돈 돼지 등뼈, 4kg, 1박스",
            "올챌린지 천연펄프 화장지, 3겹, 30m, 30롤, 2팩",
        ):
            with self.subTest(title=title):
                self.assertFalse(
                    promotions.passes_inline_quality_gate(self._item(displayName=title))
                )

    def test_keeps_student_sized_quantities(self):
        for title in (
            "펩시 제로슈거 라임 245ml 30개",
            "동원 통그릴 비엔나, 1kg, 2봉",
        ):
            with self.subTest(title=title):
                self.assertTrue(
                    promotions.passes_inline_quality_gate(self._item(displayName=title))
                )


class FixedRotationTest(unittest.TestCase):
    PRODUCTS = [("fixed_a", {"title": "A"}), ("fixed_b", {"title": "B"}), ("fixed_c", {"title": "C"})]

    def test_walks_the_admin_order_while_something_is_unseen(self):
        for seen, expected in (
            ({}, "fixed_a"),
            ({"fixed_a": datetime(2026, 9, 10, 9)}, "fixed_b"),
            ({"fixed_a": datetime(2026, 9, 10, 9), "fixed_b": datetime(2026, 9, 10, 10)}, "fixed_c"),
        ):
            with self.subTest(seen=sorted(seen)):
                key, _ = promotions._rotate_fixed_product(self.PRODUCTS, seen)
                self.assertEqual(key, expected)

    def test_restarts_from_the_least_recently_shown(self):
        seen = {
            "fixed_a": datetime(2026, 9, 10, 12),
            "fixed_b": datetime(2026, 9, 10, 8),
            "fixed_c": datetime(2026, 9, 10, 10),
        }

        key, _ = promotions._rotate_fixed_product(self.PRODUCTS, seen)

        self.assertEqual(key, "fixed_b")

    def test_ignores_products_that_are_no_longer_enabled(self):
        seen = {"fixed_a": datetime(2026, 9, 10, 9), "fixed_gone": datetime(2026, 9, 10, 11)}

        key, _ = promotions._rotate_fixed_product(self.PRODUCTS, seen)

        self.assertEqual(key, "fixed_b")


class InlineCardAudienceTest(unittest.TestCase):
    def test_enabled_for_everyone_by_default(self):
        with mock.patch.dict("os.environ", {"PROMOTION_INLINE_CARD_USER_IDS": ""}, clear=False):
            self.assertTrue(cafeteria_router._inline_card_enabled("anyone"))
            # user_id가 없으면 클릭을 귀속할 수 없어 노출하지 않는다.
            self.assertFalse(cafeteria_router._inline_card_enabled(None))

    def test_kill_switch_turns_it_off_without_a_deploy(self):
        for value in ("false", "0", "off", "NO"):
            with self.subTest(value=value):
                with mock.patch.dict("os.environ", {"PROMOTION_INLINE_CARD_ENABLED": value}):
                    self.assertFalse(cafeteria_router._inline_card_enabled("anyone"))

    def test_user_list_narrows_the_audience_when_set(self):
        with mock.patch.dict(
            "os.environ",
            {"PROMOTION_INLINE_CARD_ENABLED": "true", "PROMOTION_INLINE_CARD_USER_IDS": "tester-c"},
        ):
            self.assertTrue(cafeteria_router._inline_card_enabled("tester-c"))
            self.assertFalse(cafeteria_router._inline_card_enabled("someone-else"))


class InlineProductCardTest(unittest.TestCase):
    def test_card_mimics_the_commerce_card_price_block(self):
        card = promotions.create_inline_product_card(
            INLINE_PRODUCT, "https://cnubot.example/click?token=x"
        )
        price_block = card["description"].split("\n\n")[0]

        self.assertEqual(card["title"], INLINE_PRODUCT["title"])
        # 할인율 + 취소선 정가, 그 아래 최종가.
        self.assertTrue(price_block.startswith("74% "))
        self.assertIn("2̶9̶,̶9̶0̶0̶원̶", price_block)
        self.assertEqual(price_block.split("\n")[1], "7,500원")
        self.assertEqual(
            card["buttons"][0]["webLinkUrl"], "https://cnubot.example/click?token=x"
        )

    def test_card_matches_the_product_list_wording(self):
        output = promotions.create_inline_product_output(INLINE_PRODUCT)
        card = promotions.create_inline_product_card(INLINE_PRODUCT)

        # 퀵리플라이 목록의 카드 설명과 같은 문구를 쓴다.
        self.assertEqual(
            output["commerceCard"]["description"], "74% 할인 · 최대할인가 7,500원"
        )
        for text in (output["commerceCard"]["description"], card["description"]):
            self.assertNotIn("운영비", text)
            self.assertNotIn("수수료", text)

    def test_custom_product_description_is_kept(self):
        product = dict(INLINE_PRODUCT, description="🧻 1매당 8원 · 무료배송 특가")

        self.assertEqual(
            promotions.create_inline_product_output(product)["commerceCard"]["description"],
            "🧻 1매당 8원 · 무료배송 특가",
        )
        self.assertIn(
            "🧻 1매당 8원 · 무료배송 특가",
            promotions.create_inline_product_card(product)["description"],
        )

    def test_card_uses_the_product_button_label(self):
        card = promotions.create_inline_product_card(
            dict(INLINE_PRODUCT, button_label="🧻 물티슈 특가 · 제휴")
        )

        self.assertEqual(card["buttons"][0]["label"], "🧻 물티슈 특가")

    def test_card_stays_inside_kakao_text_card_carousel_limits(self):
        product = dict(
            INLINE_PRODUCT,
            title="일동후디스 하이뮨 프로틴 밸런스 액티브 밤티라미수 제로 250ml 18개입 대용량 기획세트 한정",
        )
        card = promotions.create_inline_product_card(product)

        self.assertLessEqual(len(card["title"]), 50)
        self.assertLessEqual(len(card["description"]), 128)
        self.assertLessEqual(len(card["buttons"][0]["label"]), 14)

    def test_card_falls_back_to_a_plain_price_without_a_discount(self):
        product = dict(INLINE_PRODUCT, original_price=7500)
        product.pop("discount_rate")
        card = promotions.create_inline_product_card(product)

        self.assertEqual(card["description"], "7,500원")
        self.assertNotIn("̶", card["description"])


class MenuInlineCardResponseTest(unittest.TestCase):
    def test_menu_keeps_three_meal_rows_without_inline_product(self):
        response = cafeteria.create_menu_response("월요일", MENU_DATA, "상록회관")
        outputs = response["template"]["outputs"]

        self.assertEqual(len(outputs), 3)
        lunch_card = outputs[1]["carousel"]["items"][0]
        self.assertEqual(len(lunch_card["buttons"]), 2)

    def test_inline_card_joins_the_lunch_row_and_keeps_three_rows(self):
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        response = cafeteria.create_menu_response(
            "월요일", MENU_DATA, "상록회관", inline_product_card=card
        )
        outputs = response["template"]["outputs"]

        # 끼니별 3행이 유지되고 상품 카드는 점심 행 끝에 붙는다.
        self.assertEqual(len(outputs), 3)
        self.assertTrue(all(o["carousel"]["type"] == "textCard" for o in outputs))
        lunch_items = outputs[1]["carousel"]["items"]
        self.assertEqual(len(lunch_items), 3)
        self.assertIs(lunch_items[2], card)
        self.assertEqual(
            [button["label"] for button in lunch_items[0]["buttons"]], ["식단 공유하기"]
        )

    def test_commerce_card_takes_the_empty_meal_slot(self):
        """빈 끼니 자리를 물려받아 아침·점심·저녁 순서가 유지된다."""
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        output = promotions.create_inline_product_output(INLINE_PRODUCT)
        cases = {
            "breakfast": (dict(MENU_DATA, breakfast=[]), 0),
            "lunch": (dict(MENU_DATA, lunch=[]), 1),
            "dinner": (dict(MENU_DATA, dinner=[]), 2),
        }
        for empty_meal, (menu_data, expected_index) in cases.items():
            with self.subTest(empty_meal=empty_meal):
                response = cafeteria.create_menu_response(
                    "월요일", menu_data, "상록회관",
                    inline_product_card=card, inline_product_output=output,
                )
                outputs = response["template"]["outputs"]

                self.assertEqual(len(outputs), 3)
                self.assertIs(outputs[expected_index], output)
                self.assertEqual(
                    outputs[expected_index]["commerceCard"]["thumbnails"],
                    [{"imageUrl": INLINE_PRODUCT["image_url"]}],
                )

    def test_commerce_card_takes_the_first_empty_slot_when_several_are_free(self):
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        output = promotions.create_inline_product_output(INLINE_PRODUCT)
        # 점심만 운영하는 식당: 아침 자리가 먼저 비어 있다.
        response = cafeteria.create_menu_response(
            "월요일", dict(MENU_DATA, breakfast=[], dinner=[]), "상록회관",
            inline_product_card=card, inline_product_output=output,
        )
        outputs = response["template"]["outputs"]

        self.assertEqual(len(outputs), 2)
        self.assertIs(outputs[0], output)
        self.assertNotIn(card, outputs[1]["carousel"]["items"])

    def test_full_three_rows_fall_back_to_the_text_card(self):
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        output = promotions.create_inline_product_output(INLINE_PRODUCT)
        response = cafeteria.create_menu_response(
            "월요일", MENU_DATA, "상록회관",
            inline_product_card=card, inline_product_output=output,
        )
        outputs = response["template"]["outputs"]

        self.assertEqual(len(outputs), 3)
        self.assertTrue(all("carousel" in output for output in outputs))
        self.assertIs(outputs[1]["carousel"]["items"][-1], card)

    def test_entry_button_returns_when_the_product_cannot_be_placed(self):
        crowded = {
            "breakfast": [{"type": f"조식{i}", "menu": ["밥"]} for i in range(3)],
            "lunch": [{"type": f"중식{i}", "menu": ["밥"]} for i in range(3)],
            "dinner": [{"type": f"석식{i}", "menu": ["밥"]} for i in range(3)],
        }
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        output = promotions.create_inline_product_output(INLINE_PRODUCT)
        response = cafeteria.create_menu_response(
            "월요일", crowded, "상록회관",
            inline_product_card=card, inline_product_output=output,
        )
        lunch_card = response["template"]["outputs"][1]["carousel"]["items"][0]

        self.assertEqual(len(lunch_card["buttons"]), 2)

    def test_placement_check_only_counts_a_card_that_survived(self):
        """노출 이벤트는 카드가 실제로 응답에 들어갔을 때만 기록되어야 한다."""
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        output = promotions.create_inline_product_output(INLINE_PRODUCT)
        inline_product = {"inline_product_card": card, "inline_product_output": output}
        crowded = {
            meal: [{"type": f"{meal}{i}", "menu": ["밥"]} for i in range(3)]
            for meal in ("breakfast", "lunch", "dinner")
        }

        placed = cafeteria.create_menu_response(
            "월요일", MENU_DATA, "상록회관", **inline_product
        )
        dropped = cafeteria.create_menu_response(
            "월요일", crowded, "상록회관", **inline_product
        )

        self.assertTrue(cafeteria_router._inline_card_placed(placed, inline_product))
        self.assertFalse(cafeteria_router._inline_card_placed(dropped, inline_product))

    def test_every_response_stays_within_the_three_output_limit(self):
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        for label, menu_data in (
            ("lunch only", dict(MENU_DATA, breakfast=[], dinner=[])),
            ("all meals", MENU_DATA),
            ("full lunch row", dict(MENU_DATA, lunch=[MENU_DATA["lunch"][0]] * 3)),
        ):
            with self.subTest(label=label):
                response = cafeteria.create_menu_response(
                    "월요일", menu_data, "상록회관", inline_product_card=card
                )
                self.assertLessEqual(len(response["template"]["outputs"]), 3)
                for output in response["template"]["outputs"]:
                    self.assertLessEqual(len(output["carousel"]["items"]), 3)

    def test_inline_card_is_dropped_when_no_row_has_space(self):
        crowded = {
            "breakfast": [{"type": f"조식{i}", "menu": ["밥"]} for i in range(3)],
            "lunch": [{"type": f"중식{i}", "menu": ["밥"]} for i in range(3)],
            "dinner": [{"type": f"석식{i}", "menu": ["밥"]} for i in range(3)],
        }
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        response = cafeteria.create_menu_response(
            "월요일", crowded, "상록회관", inline_product_card=card
        )
        items = [i for o in response["template"]["outputs"] for i in o["carousel"]["items"]]

        self.assertEqual(len(response["template"]["outputs"]), 3)
        self.assertNotIn(card, items)

    def test_inline_card_falls_back_to_dinner_when_lunch_row_is_full(self):
        menu_data = dict(MENU_DATA, lunch=[MENU_DATA["lunch"][0]] * 3)
        card = promotions.create_inline_product_card(INLINE_PRODUCT)
        response = cafeteria.create_menu_response(
            "월요일", menu_data, "상록회관", inline_product_card=card
        )

        self.assertIs(response["template"]["outputs"][2]["carousel"]["items"][-1], card)


if __name__ == "__main__":
    unittest.main()
