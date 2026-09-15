import unittest
from unittest.mock import AsyncMock, patch
from app.services import recommendation_policy as policy, promotions

TREE = {1: ["식품", "생수/음료", "생수/탄산수"],
        2: ["식품", "생수/음료", "음료", "탄산음료"],
        3: ["식품", "스낵/간식", "스낵/시리얼"],
        4: ["식품", "가공/즉석식품", "라면"],
        5: ["식품", "가공/즉석식품", "즉석밥/간편조리"],
        6: ["식품", "냉장/냉동식품", "냉장냉동 간편조리"],
        7: ["생활용품", "세제", "세탁세제", "캡슐세제"],
        8: ["생활용품", "세제", "세탁세제", "액체세제"],
        9: ["가구/홈데코", "가구", "침대"],
        10: ["생활용품", "공구", "소형기계"],
        11: ["가전/디지털", "냉장고/밥솥/주방가전", "냉장고"],
        12: ["가전/디지털", "컴퓨터/게임/SW", "키보드"],
        13: ["식품", "생수/음료", "음료", "주스"],
        14: ["식품", "생수/음료", "음료", "에너지음료"]}


def item(i, cid=1):
    return {"tacaItemId": i, "categoryIds": [cid], "displayName": "상품 " + str(i),
            "displayPrice": 5000, "originalPrice": 10000, "discountRate": 50,
            "thumbnailUrl": "https://example.com/image.jpg", "rank": i,
            "_category_names": TREE[cid]}


def select(items, affinity=None, recent=None):
    remaining = [dict(x, _policy=policy.classify(x, TREE, "food")) for x in items]
    selected = []
    while len(selected) < 6:
        chosen = policy.choose(remaining, selected, affinity or {}, recent or {})
        if not chosen:
            break
        selected.append(chosen)
        remaining = [x for x in remaining if x["tacaItemId"] != chosen["tacaItemId"]]
    return selected


class DiversityTest(unittest.TestCase):
    def test_water_only_returns_one_even_with_huge_affinity(self):
        self.assertEqual(len(select([item(i) for i in range(1, 20)], {1: 10000})), 1)

    def test_six_distinct_types_despite_water_popularity(self):
        result = select([item(i) for i in range(1, 20)] + [item(30+c, c) for c in range(2, 7)], {1: 10000})
        self.assertEqual(len(result), 6)
        self.assertEqual(len({x["_policy"]["family"] for x in result}), 6)

    def test_collection_boundaries_and_detergent_variants(self):
        for cid in (1, 9, 10, 11):
            self.assertIsNone(policy.classify(item(cid, cid), TREE, "living"))
        self.assertIsNotNone(policy.classify(item(12, 12), TREE, "living"))
        self.assertIsNone(policy.classify(item(7, 7), TREE, "food"))
        self.assertEqual(policy.classify(item(7, 7), TREE, "living")["family"],
                         policy.classify(item(8, 8), TREE, "living")["family"])

    def test_recent_water_rotates_brand_without_adding_another_water(self):
        result = select([item(1), item(2)], recent={1: 100})
        self.assertEqual([x["tacaItemId"] for x in result], [2])
        self.assertEqual([x["tacaItemId"] for x in select([item(1), item(2)], recent={1: 100, 2: 50})], [2])

    def test_affinity_is_bounded_and_not_summed(self):
        self.assertEqual(policy.affinity_score({"categoryIds": [1, 2]}, {1: 10000, 2: 10000}), 3)

    def test_group_cap_relaxes_to_three_but_never_four(self):
        result = select([item(i, c) for i, c in enumerate((1, 2, 13, 14), 1)])
        self.assertEqual(len(result), 3)
        self.assertEqual(result[-1]["_decision"]["group_limit"], 3)

    def test_supplements_cover_multiple_groups(self):
        ids = policy.supplement_categories(TREE, "food")
        self.assertGreaterEqual(len({TREE[c][1] for c in ids}), 3)

    def test_final_slot_explores_unfamiliar_type(self):
        result = select([item(10+c, c) for c in range(1, 7)], {c: 10 for c in range(1, 6)})
        self.assertEqual(result[-1]["_decision"]["reason"], "새 품목 탐색")


class SelectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_failed_detail_replenishes_and_diagnostic_does_not_record(self):
        candidates = [item(1), item(2)] + [item(20+c, c) for c in range(2, 7)]
        async def detail(cid):
            found = next(x for x in candidates if x["tacaItemId"] == cid)
            return dict(found, isSoldOut=cid == 1)
        with patch.object(promotions, "_candidate_pool", AsyncMock(return_value=candidates)), \
             patch.object(promotions.toss_sharelink, "categories", AsyncMock(return_value=TREE)), \
             patch.object(promotions.toss_sharelink, "detail", AsyncMock(side_effect=detail)), \
             patch.object(promotions.toss_sharelink, "issue_link", AsyncMock(return_value="https://toss.im/_m/test")), \
             patch.object(promotions.recommendations, "category_affinity", AsyncMock(return_value={})), \
             patch.object(promotions.recommendations, "recent_item_ids", AsyncMock(return_value={})), \
             patch.object(promotions.recommendations, "record_exposure", AsyncMock()) as exposures:
            result = await promotions.get_live_toss_products(collection_id="food", limit=6,
                force_algorithm=True, record_exposure=False)
        self.assertEqual(len(result), 6)
        self.assertNotIn(1, [p["taca_item_id"] for _, p in result])
        self.assertEqual(len({p["recommendation_diagnostic"]["family"] for _, p in result}), 6)
        exposures.assert_not_awaited()

    async def test_detail_cannot_move_food_into_living(self):
        with patch.object(promotions, "_candidate_pool", AsyncMock(return_value=[item(7, 7)])), \
             patch.object(promotions.toss_sharelink, "categories", AsyncMock(return_value=TREE)), \
             patch.object(promotions.toss_sharelink, "detail", AsyncMock(return_value=item(7, 1))), \
             patch.object(promotions.toss_sharelink, "issue_link", AsyncMock()) as links:
            result = await promotions.get_live_toss_products(collection_id="living", force_algorithm=True, record_exposure=False)
        self.assertEqual(result, [])
        links.assert_not_awaited()


class DiagnosticEndpointTest(unittest.TestCase):
    def test_authentication_and_read_only_preview(self):
        import os
        from fastapi.testclient import TestClient
        from app.app import app
        with patch.dict(os.environ, {"ADMIN_USERNAME": "test-admin", "ADMIN_PASSWORD": "test-password"}), \
             patch.object(promotions, "get_live_toss_products", AsyncMock(return_value=[])) as selector:
            client = TestClient(app)  # No lifespan/database initialization.
            self.addCleanup(client.close)
            self.assertEqual(client.get("/admin/promotion-settings/diagnostic").status_code, 401)
            response = client.get("/admin/promotion-settings/diagnostic?collection_id=food", auth=("test-admin", "test-password"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertFalse(selector.call_args.kwargs["record_exposure"])
            self.assertTrue(selector.call_args.kwargs["force_algorithm"])
