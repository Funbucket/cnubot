import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

from app.services import discount_fallback as fallback, product_snapshot as store, promotions


class DiscountFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = patch.dict(os.environ, {'MENU_DATA_DIR': self.tmp.name, 'TOSS_PUBLISHER_ID': 'test'})
        env.start()
        self.addCleanup(env.stop)
        self.snapshot = {
            'updated_at': datetime.now(store.KST).isoformat(),
            'categories': {'success': {'categories': [
                {'categoryId': 1, 'displayName': '식품', 'children': [
                    {'categoryId': 2, 'displayName': '간식', 'children': [
                        {'categoryId': 10+i, 'displayName': '간식'+str(i)} for i in range(8)]}]}]}},
            'lists': {'/openapi/products/today-deals': []},
            'items': {str(i): {'tacaItemId': i, 'displayName': '상품'+str(i),
                        'displayPrice': 1000, 'originalPrice': 2000, 'discountRate': 50,
                        'thumbnailUrl': 'https://example.com/image.jpg', 'categoryIds': [10+i]}
                      for i in range(8)},
            'links': {str(i)+':test': 'https://example.com/item/'+str(i) for i in range(8)}}

    def test_filters_and_validates_rates(self):
        items = self.snapshot['items']
        items['0']['isSoldOut'] = True
        items['1']['endAt'] = (datetime.now(store.KST)-timedelta(minutes=1)).isoformat()
        items['2']['displayPrice'] = 60000
        items['3']['discountRate'] = 20
        items['4']['originalPrice'] = 1200  # inflated declared discount
        del self.snapshot['links']['5:test']
        self.assertEqual([i['tacaItemId'] for i in fallback.candidates(self.snapshot)], [6, 7])
        self.snapshot['updated_at'] = (datetime.now(store.KST)-timedelta(hours=49)).isoformat()
        self.assertEqual(fallback.candidates(self.snapshot), [])

    def test_tiers_rotation_and_family_limits(self):
        items = fallback.candidates(self.snapshot)
        items[0]['discountRate'] = 80
        items[1]['discountRate'] = 35
        items[2]['_policy']['family'] = items[0]['_policy']['family']
        picked = fallback.choose(items, {0: 1}, 3)
        self.assertNotIn(0, [i['tacaItemId'] for i in picked])
        self.assertNotIn(1, [i['tacaItemId'] for i in picked])
        self.assertEqual(len({i['_policy']['family'] for i in picked}), len(picked))
        single = fallback.choose([items[0], items[1]], {}, 6)
        self.assertEqual([i['tacaItemId'] for i in single], [0, 1])

    def test_empty_and_failed_deals_use_disk_without_network(self):
        store.write(self.snapshot)
        for failure in (False, True):
            with self.subTest(failure=failure), \
                 patch.object(promotions.toss_sharelink, 'today_deals', AsyncMock(
                     return_value=[], side_effect=RuntimeError('unavailable') if failure else None)), \
                 patch.object(promotions.recommendations, 'recent_item_ids', AsyncMock(return_value={})), \
                 patch.object(promotions.recommendations, 'record_exposure', AsyncMock()) as exposure, \
                 patch('requests.get', side_effect=AssertionError('network')), \
                 patch('requests.post', side_effect=AssertionError('network')):
                products = asyncio.run(promotions.get_today_deal_products('test', limit=6))
                self.assertEqual(len(products), 3)  # one group, three distinct families
                self.assertTrue(all(p['selection_mode'] == 'high_discount_fallback' for _, p in products))
                self.assertEqual(exposure.call_args.kwargs['properties']['selection_mode'], 'high_discount_fallback')
                response = promotions.create_toss_shopping_list_response([p for _, p in products], collection_id='today_deals')
                self.assertIn('오늘 특가 대신', response['template']['outputs'][0]['simpleText']['text'])
                self.assertEqual(response['template']['quickReplies'][-1]['messageText'], '오늘 특가')
                from app.routers.promotions import get_today_deals
                import json
                with patch('app.routers.promotions.experiments.record_funnel_event', AsyncMock()):
                    routed = asyncio.run(get_today_deals(None))
                self.assertIn('오늘 특가 대신', json.loads(routed.body)['template']['outputs'][0]['simpleText']['text'])

    def test_admin_reports_fallback(self):
        from app.services.product_collection_status import summary
        store.write(self.snapshot)
        row = summary()['collections'][0]
        self.assertEqual(row['serving'], 'discount_fallback')
        self.assertEqual(row['discount_fallback_count'], 8)
