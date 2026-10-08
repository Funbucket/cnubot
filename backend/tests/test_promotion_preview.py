import copy
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.routers import cafeteria as menu_routes, promotions as promotion_routes
from app.schemas.kakao_request import KakaoRequest
from app.services import cafeteria, promotion_cards, promotion_preview as preview
from tests.test_menu_inline_card import MENU_DATA

ENV = {"DEVELOPER_ID": "preview-owner", "PROMOTION_BUNDLE_PREVIEW_ENABLED": "true",
       "PROMOTION_INLINE_CARD_ENABLED": "true", "PROMOTION_INLINE_CARD_USER_IDS": "",
       "PROMOTION_TRACKING_SECRET": "test-secret", "SERVER_URL": "https://example.com"}


def request(user="preview-owner", action=None):
    data = {"userRequest": {"utterance": "오늘 특가", "user": {"id": user}}}
    if action:
        data["action"] = action
    return KakaoRequest.model_validate(data)


def snapshot():
    def root(name, first_id, group, leaf, leaf_id):
        return {"categoryId": first_id, "displayName": name, "children": [
            {"categoryId": first_id+1, "displayName": group, "children": [
                {"categoryId": leaf_id, "displayName": leaf}]}]}
    categories = [root("식품", 10, "즉석/간편식", "라면", 12),
                  root("식품", 20, "과자/간식", "쿠키", 22),
                  root("생활용품", 30, "화장지/물티슈", "물티슈", 32)]
    items = {}
    for item_id, category, title, price in [
        (1, 12, "간편 라면 5개", 2500), (2, 22, "쿠키 2개", 3000),
        (3, 32, "물티슈 100매", 4000), (4, 12, "다른 라면 5개", 3500),
    ]:
        items[str(item_id)] = {
            "tacaItemId": item_id, "displayName": title, "displayPrice": price,
            "originalPrice": price*2, "discountRate": 50,
            "thumbnailUrl": "https://example.com/product.jpg", "categoryIds": [category],
            "reviewScore": 4.8, "reviewCount": 500,
        }
    return {"updated_at": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(),
            "categories": {"success": {"categories": categories}}, "items": items,
            "links": {f"{i}:test-publisher": "https://toss.im/_m/test" for i in range(1,5)}}


def chosen():
    pairs = preview.select_products(snapshot(), "test-publisher", {})
    for _, product in pairs:
        product["settings_revision"] = 1
    return pairs, ["https://example.com/click"]*len(pairs), "test-request"


class PreviewAudienceTest(unittest.TestCase):
    def test_only_configured_owner_can_see_preview(self):
        with patch.dict("os.environ", ENV):
            self.assertTrue(preview.enabled("preview-owner"))
            self.assertFalse(preview.enabled("someone-else"))
            self.assertFalse(preview.enabled(None))

    def test_empty_id_or_disabled_flag_fails_closed(self):
        for overrides in [{"DEVELOPER_ID": ""}, {"PROMOTION_BUNDLE_PREVIEW_ENABLED": "false"},
                          {"PROMOTION_BUNDLE_PREVIEW_ENABLED": ""}]:
            with self.subTest(overrides=overrides), patch.dict("os.environ", {**ENV, **overrides}):
                self.assertFalse(preview.enabled("preview-owner"))


class PreviewSelectionTest(unittest.TestCase):
    def test_student_size_excludes_heavy_liquid_and_weight_bundles(self):
        self.assertFalse(preview._student_sized("섬유유연제 2.5L, 4개", "living"))
        self.assertFalse(preview._student_sized("생수 2L, 6개", "snack"))
        self.assertFalse(preview._student_sized("즉석식품 1kg, 3개", "meal"))
        self.assertTrue(preview._student_sized("음료 250ml, 12개", "snack"))
        self.assertTrue(preview._student_sized("물티슈 100매", "living"))

    def test_distinct_student_slots_are_cheap_and_linked(self):
        pairs, _, _ = chosen()
        self.assertEqual([p["preview_slot"] for _, p in pairs], ["meal", "snack", "living"])
        self.assertEqual(len({p["preview_family"] for _, p in pairs}), 3)
        self.assertTrue(all(p["price"]<=10000 and p["url"] for _,p in pairs))

    def test_excludes_expired_unlinked_sold_out_and_too_expensive_items(self):
        for field,value in [("isSoldOut",True), ("displayPrice",12000),
                            ("endAt",(datetime.now(ZoneInfo("Asia/Seoul"))-timedelta(seconds=1)).isoformat())]:
            data=snapshot();data["items"]["3"][field]=value
            with self.subTest(field=field):
                self.assertNotIn("preview_toss_item_3", [k for k,_ in preview.select_products(data,"test-publisher",{})])
        data=snapshot();data["links"].pop("3:test-publisher")
        self.assertNotIn("preview_toss_item_3", [k for k,_ in preview.select_products(data,"test-publisher",{})])
        data["updated_at"]=(datetime.now(ZoneInfo("Asia/Seoul"))-timedelta(hours=49)).isoformat()
        self.assertEqual(preview.select_products(data,"test-publisher",{}),[])

    def test_discount_does_not_exceed_actual_price_difference(self):
        data=snapshot();data["items"]["3"].update(originalPrice=4100,discountRate=90)
        self.assertNotIn("preview_toss_item_3", [k for k,_ in preview.select_products(data,"test-publisher",{})])

    def test_refresh_rotates_unseen_items_without_duplicate_family(self):
        pairs=preview.select_products(snapshot(),"test-publisher",{
            "preview_toss_item_1":datetime.now(ZoneInfo("Asia/Seoul"))})
        self.assertEqual(pairs[0][0],"preview_toss_item_4")
        self.assertEqual(len({p["preview_family"] for _,p in pairs}),len(pairs))

    def test_fewer_candidates_produce_fewer_cards(self):
        data=snapshot();data["items"]={"3":data["items"]["3"]}
        self.assertEqual(len(preview.select_products(data,"test-publisher",{})),1)


class PreviewOutputTest(unittest.TestCase):
    def test_one_output_contains_three_valid_cards_and_existing_messages(self):
        pairs,urls,_=chosen()
        output=promotion_cards.create_inline_bundle_output([p for _,p in pairs],urls)
        self.assertEqual(output["carousel"]["type"],"commerceCard")
        self.assertEqual(len(output["carousel"]["items"]),3)
        for card in output["carousel"]["items"]:
            self.assertLessEqual(len(card["title"]),30)
            self.assertLessEqual(len(card["description"]),40)
            self.assertIn("제휴",card["description"])
            self.assertLessEqual(len(card["buttons"]),3)
            self.assertIn(card["buttons"][1]["messageText"],["자취생 먹을거 핫딜","자취생 꿀템"])


class PreviewRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_today_deals_keeps_six_products_for_owner_and_other_users(self):
        for user in ["preview-owner", "someone-else"]:
            with self.subTest(user=user), patch.dict("os.environ", ENV), \
                 patch.object(preview, "pick", new=AsyncMock()) as pick, \
                 patch.object(promotion_routes.promotions, "get_today_deal_products", new=AsyncMock(return_value=[])) as normal, \
                 patch.object(promotion_routes.experiments, "record_funnel_event", new=AsyncMock()):
                await promotion_routes.get_today_deals(request(user))
            pick.assert_not_awaited()
            normal.assert_awaited_once()
            self.assertEqual(normal.await_args.kwargs["limit"], 6)

    async def test_automatic_preview_obeys_daily_cap_and_storage_failure(self):
        for result in [True,RuntimeError("storage unavailable")]:
            cap=AsyncMock(side_effect=result) if isinstance(result,Exception) else AsyncMock(return_value=result)
            with patch.dict("os.environ",ENV), patch.object(menu_routes.promotions,"has_inline_exposure_today",new=cap), \
                 patch.object(preview,"pick",new=AsyncMock()) as pick:
                self.assertIsNone(await menu_routes._pick_preview_bundle("preview-owner"))
            pick.assert_not_awaited()

    async def test_non_owner_never_selects_private_bundle(self):
        with patch.dict("os.environ",ENV), patch.object(preview,"pick",new=AsyncMock()) as pick:
            self.assertIsNone(await menu_routes._pick_preview_bundle("someone-else"))
        pick.assert_not_awaited()

    async def _menu(self, menu, record_result=True, restore=False):
        req=request(action={"clientExtra":{"show_breakfast":True}} if restore else None)
        with patch.dict("os.environ",ENV), \
             patch.object(menu_routes,"_pick_preview_bundle",new=AsyncMock(return_value=chosen())) as pick, \
             patch.object(menu_routes,"_pick_inline_product",new=AsyncMock(return_value=None)), \
             patch.object(preview,"record",new=AsyncMock(return_value=record_result)) as record, \
             patch.object(menu_routes,"_record_menu_view",new=AsyncMock()), \
             patch.object(menu_routes,"_record_promotion_button_exposures",new=AsyncMock()):
            response=await menu_routes._menu_response(req,"월요일",menu,"상록회관","sangrok")
        return response,record,pick

    async def test_inline_bundle_fits_one_empty_slot_and_records_once(self):
        response,record,_=await self._menu(dict(MENU_DATA,breakfast=[]))
        outputs=response["template"]["outputs"]
        self.assertEqual(len(outputs),3)
        self.assertEqual(outputs[0]["carousel"]["type"],"commerceCard")
        record.assert_awaited_once()
        self.assertTrue(record.await_args.kwargs["daily_cap"])

    async def test_full_menu_does_not_record_dropped_bundle(self):
        response,record,_=await self._menu(MENU_DATA)
        self.assertEqual(response,cafeteria.create_menu_response("월요일",MENU_DATA,"상록회관"))
        record.assert_not_awaited()

    async def test_lost_daily_slot_restores_original_menu(self):
        response,_,_=await self._menu(dict(MENU_DATA,breakfast=[]),record_result=False)
        self.assertTrue(all(o.get("carousel",{}).get("type")!="commerceCard" for o in response["template"]["outputs"]))

    async def test_restore_request_does_not_pick_preview(self):
        response,record,pick=await self._menu(MENU_DATA,restore=True)
        pick.assert_not_awaited();record.assert_not_awaited()
        self.assertEqual(response,cafeteria.create_menu_response("월요일",MENU_DATA,"상록회관"))

    async def test_finished_breakfast_restore_is_available_on_each_preview_card(self):
        pairs,urls,_=chosen()
        output={"inline_product_output":promotion_cards.create_inline_bundle_output([p for _,p in pairs],urls)}
        with patch.object(cafeteria,"dorm_meal_hours",new=AsyncMock(return_value={})), \
             patch.object(cafeteria,"is_meal_time_over",return_value=True):
            menu,inline=await menu_routes._replace_finished_breakfast(copy.deepcopy(MENU_DATA),output,"기숙사")
        self.assertEqual(menu["breakfast"],[])
        self.assertEqual(menu["lunch"],MENU_DATA["lunch"])
        for card in inline["inline_product_output"]["carousel"]["items"]:
            self.assertEqual(len(card["buttons"]),3)
            self.assertTrue(card["buttons"][-1]["extra"]["show_breakfast"])
