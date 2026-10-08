import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.schemas.experiment_lab import DesignInput, Protocol, AnalysisInput
from app.services import experiment_lab as lab, lab_stats, recommendations, lab_delivery

UTC=timezone.utc


class LabStatisticsTest(unittest.TestCase):
    def test_newcombe_matches_independent_statsmodels(self):
        from statsmodels.stats.proportion import confint_proportions_2indep
        for a,na,b,nb in [(8,1100,35,1100),(0,100,4,101),(0,100,0,100),(100,100,100,100),(1,3,0,4)]:
            effect=lab_stats.click_effect(a,na,b,nb)
            lo,hi=confint_proportions_2indep(b,nb,a,na,method='newcomb')
            self.assertAlmostEqual(effect['ci_low'],lo,places=12)
            self.assertAlmostEqual(effect['ci_high'],hi,places=12)
        self.assertIsNone(lab_stats.click_effect(0,0,1,10))

    def test_fisher_reference_and_zero_cells(self):
        effect=lab_stats.click_effect(6,8,1,5)
        self.assertAlmostEqual(effect['p_value'],0.10256410256410256,places=12)
        self.assertEqual(lab_stats.click_effect(0,100,0,100)['p_value'],1)
        self.assertIsNone(lab_stats.click_effect(0,100,0,100)['relative_change'])

    def test_welch_matches_independent_ttest(self):
        from scipy.stats import ttest_ind
        a,b=[1,2,4,5,1],[2,5,7,1,4,3]
        effect=lab_stats.welch(a,b)
        ci=ttest_ind(b,a,equal_var=False).confidence_interval()
        self.assertAlmostEqual(effect['ci_low'],ci.low,places=12)
        self.assertAlmostEqual(effect['ci_high'],ci.high,places=12)
        self.assertIsNone(lab_stats.welch([0,0],[0,0]))

    def test_insufficient_srm_is_not_pass(self):
        self.assertEqual(lab_stats.assignment_quality(0,0)['status'],'pending')
        self.assertEqual(lab_stats.assignment_quality(110,0)['status'],'fail')

    def test_protocol_and_assignment(self):
        with self.assertRaises(ValueError):
            Protocol(baseline_rate=.99,target_effect=.025)
        with self.assertRaises(ValueError):
            Protocol(minimum_ci_lower=.02,minimum_effect=.01)
        self.assertEqual(lab.choose_variant('key','salt','synthetic'),lab.choose_variant('key','salt','synthetic'))
        with patch.dict(os.environ,{'DEVELOPER_ID':'synthetic-qa'}):
            self.assertTrue(lab.is_qa('synthetic-qa'))
            self.assertTrue(lab.is_qa(None))
        p=Protocol().model_dump(mode='json')
        self.assertEqual(lab.canonical_hash(p),lab.canonical_hash(dict(reversed(list(p.items())))))


@unittest.skipUnless(os.getenv('LAB_TEST_DATABASE_URL'), 'isolated PostgreSQL required')
class LabDatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncpg
        import uuid
        from pathlib import Path
        self.schema='lab_test_'+uuid.uuid4().hex
        self.url=os.environ['LAB_TEST_DATABASE_URL']
        conn=await asyncpg.connect(self.url)
        await conn.execute(f'CREATE SCHEMA {self.schema}')
        await conn.close()
        async def initialize(c):
            await c.execute(f'SET search_path TO {self.schema}')
        self.pool=await asyncpg.create_pool(self.url,min_size=1,max_size=4,init=initialize)
        # SET search_path is reset when a pooled connection is released, so use server_settings.
        await self.pool.close()
        self.pool=await asyncpg.create_pool(self.url,min_size=1,max_size=4,server_settings={'search_path':self.schema})
        await self.pool.execute((Path(__file__).parents[1]/'app/migrations/001_experiment_lab.sql').read_text())
        await self.pool.execute('''CREATE TABLE user_events(event_id TEXT PRIMARY KEY,user_id TEXT,surface TEXT,
             taca_item_id BIGINT,event_name TEXT,product_key TEXT,request_id TEXT,properties JSONB DEFAULT '{}',
             created_at TIMESTAMPTZ DEFAULT NOW())''')
        self.patches=[patch.object(lab,'get_pool',return_value=self.pool),
                      patch.object(recommendations,'get_pool',return_value=self.pool),
                      patch.object(lab_delivery,'get_pool',return_value=self.pool)]
        for p in self.patches:p.start()
        self.eid=await lab.create(DesignInput(name='Synthetic',hypothesis='Synthetic policy test',kind='aa',
            protocol=Protocol(p95_limit_ms=1000,minimum_bundle_completion=.8,
                              readiness_notes='synthetic verified',device_qa_notes='synthetic verified')), 'test')
        await lab.enrollment(self.eid,'start','synthetic test','test')

    async def asyncTearDown(self):
        for p in self.patches:p.stop()
        await self.pool.close()
        import asyncpg
        conn=await asyncpg.connect(self.url)
        await conn.execute(f'DROP SCHEMA {self.schema} CASCADE')
        await conn.close()

    async def test_concurrent_assignment_and_bundle_claim(self):
        contexts=await asyncio.gather(*[lab.assign('synthetic-user','dorm',f'request-{i}','/cafeteria/menu/day') for i in range(2)])
        self.assertEqual(len({c['variant'] for c in contexts}),1)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM lab_assignments'),1)
        items=[dict(product_key=f'product-{i}',taca_item_id=i,category_ids=[],properties={'position':i}) for i in range(1,4)]
        results=await asyncio.gather(*[recommendations.record_bundle_exposure(
            'synthetic-user','menu_inline_card',items,f'request-{i}',lab_bundle={
                'experiment_id':self.eid,'bundle_id':f'bundle-{i}','planned_variant':'B','rendered_policy':'bundle'}) for i in range(2)])
        self.assertEqual(sum(results),1)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM lab_bundles'),1)
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM user_events'),3)

    async def test_pause_and_close_keep_existing_assignment(self):
        first=await lab.assign('synthetic-user','dorm','one','/cafeteria/menu/day')
        await lab.enrollment(self.eid,'pause','synthetic pause','test')
        self.assertIsNone(await lab.assign('new-user','dorm','two','/cafeteria/menu/day'))
        existing=await lab.assign('synthetic-user','dorm','three','/cafeteria/menu/day')
        self.assertEqual(existing['variant'],first['variant'])
        await lab.enrollment(self.eid,'close','synthetic close','test')
        self.assertEqual((await lab.assign('synthetic-user','dorm','four','/cafeteria/menu/day'))['variant'],first['variant'])
        await lab.stop(self.eid,'synthetic emergency','test')
        self.assertIsNone(await lab.assign('synthetic-user','dorm','five','/cafeteria/menu/day'))

    async def test_itt_boundaries_all_sources_and_qa_exclusion(self):
        now=datetime.now(UTC)
        t0=now-timedelta(days=9)
        for user,v in [('mature-a','A'),('mature-b','B'),('active-b','B')]:
            await self.pool.execute('''INSERT INTO lab_assignments(experiment_id,user_id,variant,assigned_at,
                  pre_activity_days,first_place,eligibility_version) VALUES($1,$2,$3,$4,0,'dorm','v1')''',
                  self.eid,user,v,now-timedelta(hours=1) if user=='active-b' else t0)
        events=[('at-start','mature-a',t0,{}),('outside','mature-b',t0+timedelta(hours=168),{}),
                ('before','mature-b',t0-timedelta(seconds=1),{}),
                ('qa','mature-b',t0+timedelta(hours=1),{'is_preview':True})]
        for event,user,at,properties in events:
            await self.pool.execute('''INSERT INTO user_events(event_id,user_id,event_name,created_at,properties)
                      VALUES($1,$2,'commerce_card_click',$3,$4::jsonb)''',event,user,at,json.dumps(properties))
        # A has no exposure records: it remains in the denominator and its direct-list click counts.
        rows=await self.pool.fetch(lab.COHORT_SQL,self.eid,now)
        self.assertEqual(len(rows),2)
        self.assertTrue(next(r for r in rows if r['variant']=='A')['clicked'])
        self.assertFalse(next(r for r in rows if r['variant']=='B')['clicked'])
        await lab.enrollment(self.eid,'close','synthetic close','test')
        payload=AnalysisInput(watermark=now,idempotency_key='stable',data_complete=False,reason='synthetic watermark')
        run=await lab.run_analysis(self.eid,payload,'test')
        self.assertEqual(run['result']['assigned'],{'A':1,'B':2})
        self.assertEqual(run['result']['mature'],{'A':1,'B':1})
        self.assertFalse(run['result']['decision_ready'])
        self.assertEqual(run['id'],(await lab.run_analysis(self.eid,payload,'test'))['id'])

    async def test_qa_and_consumed_cap_do_not_enroll(self):
        with patch.dict(os.environ,{'DEVELOPER_ID':'synthetic-qa'}):
            self.assertIsNone(await lab.assign('synthetic-qa','dorm','qa','/cafeteria/menu/day'))
        await recommendations.record_exposure_once_today('already-served','menu_inline_card',1,[],product_key='product')
        self.assertIsNone(await lab.assign('already-served','dorm','next','/cafeteria/menu/day'))
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM lab_assignments'),0)

    async def test_protocol_lock_and_start_gate(self):
        with self.assertRaises(ValueError):
            await lab.update_draft(self.eid,DesignInput(name='Changed',hypothesis='Changed policy'), 'test')
        eid=await lab.create(DesignInput(name='Missing',hypothesis='No verified inputs'), 'test')
        with self.assertRaisesRegex(ValueError,'시작 게이트'):
            await lab.enrollment(eid,'start','attempt missing inputs','test')

    async def test_final_readiness_does_not_require_significance(self):
        now=datetime.now(UTC)
        t0=now-timedelta(days=9)
        await self.pool.execute('UPDATE lab_experiments SET started_at=$2 WHERE id=$1',self.eid,t0)
        for i in range(100):
            await self.pool.execute('''INSERT INTO lab_assignments(experiment_id,user_id,variant,assigned_at,
                pre_activity_days,first_place,eligibility_version) VALUES($1,$2,$3,$4,0,'dorm','v1')''',
                self.eid,f'synthetic-{i}','A' if i<50 else 'B',t0)
        await self.pool.execute('''INSERT INTO lab_requests(request_id,experiment_id,user_id,variant,route,
              completed_at,latency_ms,error,response_included) VALUES('completed',$1,'synthetic-0','A',
              '/cafeteria/menu/day',NOW(),20,FALSE,TRUE)''',self.eid)
        await lab.enrollment(self.eid,'close','synthetic close','test')
        run=await lab.run_analysis(self.eid,AnalysisInput(watermark=now,idempotency_key='final',
                  data_complete=True,reason='synthetic complete collection'),'test')
        self.assertEqual(run['result']['effect']['p_value'],1)
        self.assertTrue(run['result']['decision_ready'])
        self.assertFalse(run['result']['sample_ok'])
        self.assertEqual((await lab.get_design(self.eid))['status'],'ready')

    async def test_developer_override_is_consumed_once_without_daily_cap(self):
        from unittest.mock import AsyncMock
        product={'title':'Synthetic product','url':'https://example.com/product','price':1000,
                 'image_url':'https://example.com/image.png','taca_item_id':1,'category_ids':[]}
        with patch.dict(os.environ,{'DEVELOPER_ID':'synthetic-qa','PROMOTION_TRACKING_SECRET':'test-only-secret'}), \
             patch.object(lab_delivery,'student_pairs',new=AsyncMock(return_value=[('product',product)])):
            await lab_delivery.reserve(self.eid,'B','test')
            self.assertTrue(await lab_delivery.pending('synthetic-qa'))
            deliveries=await asyncio.gather(*[lab_delivery.consume(('product',product,'unused',f'qa-{i}'),'synthetic-qa') for i in range(2)])
            delivery=next(d for d in deliveries if d)
            self.assertEqual(sum(d is not None for d in deliveries),1)
            self.assertTrue(await lab_delivery.record(delivery))
            self.assertFalse(await recommendations.has_promotion_exposure_today('synthetic-qa','menu_inline_card'))
            self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM lab_assignments'),0)

    async def test_aa_runs_for_seven_days_instead_of_ab_sample_cap(self):
        await self.pool.execute("UPDATE lab_experiments SET protocol=jsonb_set(protocol,'{total_users}','100') WHERE id=$1",self.eid)
        for i in range(100):
            await self.pool.execute("""INSERT INTO lab_assignments(experiment_id,user_id,variant,pre_activity_days,first_place,eligibility_version)
                      VALUES($1,$2,'A',0,'dorm','v1')""",self.eid,f'aa-synthetic-{i}')
        self.assertIsNotNone(await lab.assign('aa-extra','dorm','extra','/cafeteria/menu/day'))
        self.assertEqual((await lab.get_design(self.eid))['status'],'running')
        await self.pool.execute("UPDATE lab_experiments SET started_at=NOW()-INTERVAL '8 days' WHERE id=$1",self.eid)
        self.assertIsNone(await lab.assign('too-late','dorm','late','/cafeteria/menu/day'))
        self.assertEqual((await lab.get_design(self.eid))['status'],'observing')



class LabDeliveryTest(unittest.IsolatedAsyncioTestCase):
    async def test_b_without_candidates_keeps_assignment_and_uses_common_a(self):
        from unittest.mock import AsyncMock
        product={'title':'Synthetic A','url':'https://example.com/product','price':1000,'image_url':'https://example.com/a.png'}
        context={'experiment_id':1,'variant':'B','kind':'ab','config_hash':'synthetic',
                 'policy_checksum':lab.policy_checksum(),'request_id':'synthetic-request'}
        with patch.object(lab,'assign',new=AsyncMock(return_value=context)), \
             patch.object(lab_delivery,'student_pairs',new=AsyncMock(return_value=[])), \
             patch.dict(os.environ,{'PROMOTION_TRACKING_SECRET':'test-only-secret'}):
            d=await lab_delivery.select(('synthetic-key',product,'old-url','synthetic-request'),'synthetic-user','dorm')
        self.assertEqual(d['metadata']['planned_variant'],'B')
        self.assertEqual(d['metadata']['fallback_reason'],'no_bundle_candidates')
        self.assertEqual(len(d['pairs']),1)

    async def test_signed_qa_click_and_known_bot_filter(self):
        from unittest.mock import AsyncMock
        from starlette.requests import Request
        from app.routers import promotions as routes
        from app.services import promotions
        with patch.dict(os.environ,{'PROMOTION_TRACKING_SECRET':'test-only-secret'}), \
             patch.object(routes.experiments,'record_funnel_event',new=AsyncMock()) as event, \
             patch.object(routes.recommendations,'record_category_click',new=AsyncMock()) as affinity:
            token=promotions.create_tracking_token('synthetic-qa','synthetic-key',target_url='https://example.com/product',
                      product_snapshot={'is_preview':True,'preview_session_id':'synthetic-session'})
            await routes.track_toss_shopping_click(token)
            self.assertTrue(event.await_args.kwargs['properties']['is_preview'])
            affinity.assert_not_awaited()
            event.reset_mock()
            req=Request({'type':'http','headers':[(b'user-agent',b'Kakao Preview Bot')]})
            await routes.track_toss_shopping_click(token,req)
            self.assertEqual(event.await_count,1)
            self.assertEqual(event.await_args.args[1],'commerce_card_click_raw')


class LabAdminApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_auth_action_header_and_plan_round_trip(self):
        import httpx
        from unittest.mock import AsyncMock
        from app.app import app
        with patch.dict(os.environ,{'ADMIN_USERNAME':'synthetic-admin','ADMIN_PASSWORD':'test-only-password'}), \
             patch.object(lab,'create',new=AsyncMock(return_value=123)) as create:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://example.test') as client:
                self.assertEqual((await client.get('/admin/api/experiments')).status_code,401)
                body={'name':'Synthetic API','hypothesis':'Synthetic API validation','kind':'aa','protocol':{}}
                auth=('synthetic-admin','test-only-password')
                self.assertEqual((await client.post('/admin/api/experiments',json=body,auth=auth)).status_code,403)
                response=await client.post('/admin/api/experiments',json=body,auth=auth,headers={'X-Experiment-Admin':'1'})
                self.assertEqual(response.json(),{'id':123})
                self.assertEqual(create.await_args.args[0].protocol.total_users,2200)
                invalid={**body,'protocol':{'baseline_rate':.99,'target_effect':.025}}
                self.assertEqual((await client.post('/admin/api/experiments',json=invalid,auth=auth,
                     headers={'X-Experiment-Admin':'1'})).status_code,422)
                self.assertEqual((await client.get('/admin/experiments',auth=auth)).status_code,200)
