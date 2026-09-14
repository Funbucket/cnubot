import unittest
from unittest.mock import AsyncMock, patch
from app.services import promotions as p, promotion_settings as s, promotion_cards
from app.routers import promotions as routes
from app.schemas.kakao_request import KakaoRequest


class FoodInlineTests(unittest.IsolatedAsyncioTestCase):
    def settings(self, mode='fixed'):
        products = [s.Product(title=name, url='https://toss.im/_m/'+name, enabled=enabled)
                    for name, enabled in [('hidden', False), ('first', True), ('second', True)]]
        return s.Settings(collections={'food': s.CollectionSettings(label='먹거리', message_text='자취생 먹을거 핫딜', mode=mode, products=products),
                                      'living': s.CollectionSettings(label='꿀템', message_text='자취생 꿀템')})

    async def test_fixed_rotates_through_food_and_does_not_record_before_placement(self):
        async def resolve(settings):
            self.assertEqual([x.title for x in settings.products], ['first', 'second'])
            return [('fixed_first', {'title': 'first', 'price': 1000, 'image_url': 'https://example.com/a', 'url': 'https://toss.im/_m/first'}), ('fixed_second', {'title': 'second', 'price': 1000, 'image_url': 'https://example.com/b', 'url': 'https://toss.im/_m/second'})]
        with patch.object(s, 'read_settings', return_value=self.settings()), patch.object(s, 'resolved_fixed_products', side_effect=resolve), patch.object(p.recommendations, 'last_exposure_by_product', new=AsyncMock(return_value={})), patch.object(p.recommendations, 'record_exposure', new_callable=AsyncMock) as exposure:
            key, product = await p.get_inline_promotion_product('test')
            self.assertEqual((key, product['collection_id'], product['selection_mode']), ('fixed_first', 'food', 'fixed'))
            exposure.assert_not_awaited()
            with patch.object(s, 'read_collection', return_value=self.settings().collections['food']):
                buttons = promotion_cards.create_inline_product_output(product)['commerceCard']['buttons']
                self.assertEqual([b['label'] for b in buttons], ['특가 바로가기', '먹거리 더 보기'])
            self.assertEqual(buttons[1]['messageText'], '자취생 먹을거 핫딜')

    async def test_sold_out_first_rotates_to_next_renderable_product(self):
        products = [('first', {'price':1000, 'image_url':'x', 'is_sold_out':True}), ('second', {'price':1000, 'image_url':'y', 'is_sold_out':False})]
        with patch.object(s, 'read_settings', return_value=self.settings()), patch.object(s, 'resolved_fixed_products', new=AsyncMock(return_value=products)), patch.object(p.recommendations, 'last_exposure_by_product', new=AsyncMock(return_value={})), patch.object(p.recommendations, 'latest_exposure_collection', new=AsyncMock(return_value=None)):
            key, _ = await p.get_inline_promotion_product('test')
            self.assertEqual(key, 'second')

    async def test_fixed_collections_alternate_by_priority_chain(self):
        settings = self.settings()
        living_product = s.Product(title='living', url='https://toss.im/_m/living')
        settings.collections['living'] = s.CollectionSettings(
            label='꿀템', message_text='자취생 꿀템', mode='fixed',
            products=[living_product], next_collection_id='food'
        )
        with patch.object(s, 'read_settings', return_value=settings), \
             patch.object(p.recommendations, 'latest_exposure_collection', new=AsyncMock(return_value='food')), \
             patch.object(p.recommendations, 'last_exposure_by_product', new=AsyncMock(return_value={})), \
             patch.object(s, 'resolved_fixed_products', new=AsyncMock(return_value=[('fixed_living', {'title':'living', 'price':1000, 'image_url':'y', 'url':'https://toss.im/_m/living'})])):
            key, product = await p.get_inline_promotion_product('test')
            self.assertEqual((key, product['collection_id']), ('fixed_living', 'living'))

    async def test_auto_filters_nonfood_before_ranking_and_rechecks_detail(self):
        food = {'tacaItemId': 1, 'displayName':'간식', 'displayPrice':1000, 'originalPrice':2000, 'discountRate':50, 'thumbnailUrl':'https://example.com/a', 'categoryIds':[1], '_category_names':['식품','간식']}
        nonfood = {**food, 'tacaItemId':2, 'displayName':'차량용품', '_category_names':['자동차용품']}
        def rank(candidates, *args):
            self.assertEqual(candidates, [food])
            return candidates[0]
        with patch.object(s,'read_settings',return_value=self.settings('algorithm')), patch.object(p,'_candidate_pool',new=AsyncMock(return_value=[nonfood,food])), patch.object(p.recommendations,'category_affinity',new=AsyncMock(return_value={})), patch.object(p.recommendations,'recent_item_ids',new=AsyncMock(return_value=[])), patch.object(p.recommendations,'rank_candidates',side_effect=rank), patch.object(p.toss_sharelink,'detail',new=AsyncMock(return_value=food)), patch.object(p.toss_sharelink,'categories',new=AsyncMock(return_value={1:['식품','간식']})), patch.object(p.toss_sharelink,'issue_link',new=AsyncMock(return_value='https://toss.im/_m/food')):
            _, product = await p.get_inline_promotion_product('test')
            self.assertEqual(product['collection_id'], 'food')
            self.assertEqual(product['selection_mode'], 'algorithm')

    async def test_click_preserves_signed_collection_and_surface(self):
        product={'title':'first','collection_id':'food','selection_mode':'fixed','settings_revision':3,'button_label':'특가 바로가기'}
        with patch.object(p,'_tracking_secret',return_value=b'test-only-key'), patch.object(routes.recommendations,'record_category_click',new_callable=AsyncMock), patch.object(routes.experiments,'record_funnel_event',new_callable=AsyncMock) as event:
            token=p.create_tracking_token('test','fixed_first','menu_inline',target_url='https://toss.im/_m/first',surface=p.INLINE_CARD_SURFACE,product_snapshot=product)
            response=await routes.track_toss_shopping_click(token)
            self.assertEqual(response.status_code,302)
            props=event.await_args.kwargs['properties']
            self.assertEqual((props['collection_id'],props['surface']),('food','menu_inline_card'))
        req=KakaoRequest.model_validate({'userRequest':{'utterance':'자취생 먹을거 핫딜'},'action':{'clientExtra':{'source':'menu_inline_more','button_id':'food_inline_more'}}})
        self.assertEqual(routes._promotion_entry_metadata(req)['source'],'menu_inline_more')


if __name__ == '__main__':
    unittest.main()
