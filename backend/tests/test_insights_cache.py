"""Cache concurrency, comparison windows and independently authenticated BI reports."""
import asyncio
import os
import unittest
from datetime import date,datetime,timedelta
from unittest.mock import AsyncMock,patch
import httpx
from fastapi import FastAPI
from app.routers import admin, admin_pages, insights_api
from app.services import fortune_insights
from app.services import insights_cache,insights_overview


class CacheTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        insights_cache._values.clear();insights_cache._pending.clear()

    async def test_concurrent_requests_share_one_query(self):
        async def load():
            await asyncio.sleep(.01)
            return {'ok':True}
        loader=AsyncMock(side_effect=load)
        values=await asyncio.gather(*[insights_cache.cached(('same',),loader) for _ in range(10)])
        loader.assert_awaited_once();self.assertTrue(all(v=={'ok':True} for v in values))

    async def test_failure_is_not_cached_and_exclusion_setting_is_part_of_key(self):
        loader=AsyncMock(side_effect=[RuntimeError('synthetic'),1,2,3])
        with self.assertRaises(RuntimeError):await insights_cache.cached(('key',),loader)
        self.assertEqual(await insights_cache.cached(('key',),loader),1)
        with patch.dict(os.environ,{'EXPERIMENT_QA_IDS':'synthetic-new-excluded'}):
            self.assertEqual(await insights_cache.cached(('key',),loader),2)
        self.assertEqual(await insights_cache.cached(('key',),loader,refresh=True),3)

    async def test_cancelled_reader_does_not_cancel_shared_work(self):
        gate=asyncio.Event()
        async def load():await gate.wait();return 7
        loader=AsyncMock(side_effect=load)
        first=asyncio.create_task(insights_cache.cached(('key',),loader))
        await asyncio.sleep(0)
        second=asyncio.create_task(insights_cache.cached(('key',),loader))
        first.cancel();gate.set()
        with self.assertRaises(asyncio.CancelledError):await first
        self.assertEqual(await second,7);loader.assert_awaited_once()


class ComparisonTests(unittest.TestCase):
    def test_today_compares_same_elapsed_time_of_previous_period(self):
        now=datetime(2026,10,21,14,30,tzinfo=insights_overview.KST)
        begin,finish,prior_begin,prior_finish=insights_overview.bounds(date(2026,10,15),date(2026,10,21),now)
        self.assertEqual(finish-begin,prior_finish-prior_begin)
        self.assertEqual(prior_begin.date(),date(2026,10,8))
        self.assertEqual(prior_finish,now-timedelta(days=7))

    def test_all_time_has_no_fabricated_comparison(self):
        self.assertEqual(insights_overview.bounds(None,None)[2:],(None,None))
        insights_overview.bounds(date.min,date.max)


class DashboardRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app=FastAPI();self.app.include_router(admin_pages.router,prefix='/admin')
        self.app.include_router(insights_api.router,prefix='/admin')
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),base_url='https://example.com')
        self.env=patch.dict(os.environ,{'ADMIN_USERNAME':'synthetic','ADMIN_PASSWORD':'synthetic-password','ADMIN_WEB_ORIGIN':'https://admin.example.com'});self.env.start()
        self.auth=('synthetic','synthetic-password')
        insights_cache._values.clear();insights_cache._pending.clear()

    async def asyncTearDown(self):await self.client.aclose();self.env.stop()

    async def test_shell_never_executes_promotion_queries(self):
        with patch.object(admin.experiments,'get_promotion_insights',AsyncMock(side_effect=AssertionError('eager query'))) as query:
            response=await self.client.get('/admin/insights',auth=self.auth)
        self.assertEqual(response.status_code,303);query.assert_not_called()
        self.assertEqual(response.headers['location'],'https://admin.example.com/admin/insights')
        self.assertIn('no-store',response.headers['cache-control'])

    async def test_every_report_and_personal_source_requires_auth(self):
        for endpoint in ['overview','restaurants','shuttle','products','quality','fortune','fortune-users']:
            response=await self.client.get('/admin/insights/api/'+endpoint)
            self.assertEqual(response.status_code,401)

    async def test_visual_fortune_does_not_decrypt_recent_users(self):
        with patch.object(fortune_insights,'summary',AsyncMock(return_value={})) as query:
            response=await self.client.get('/admin/insights/api/fortune',auth=self.auth)
        self.assertEqual(response.status_code,200)
        self.assertFalse(query.await_args.kwargs['include_recent'])
        self.assertNotIn('recent_users',response.json()['data'])

    async def test_invalid_dates_do_not_hit_database(self):
        with patch.object(insights_overview,'summary',AsyncMock()) as query:
            response=await self.client.get('/admin/insights/api/overview?start_date=2026-10-21&end_date=2026-10-01',auth=self.auth)
        self.assertEqual(response.status_code,400);query.assert_not_called()

@unittest.skipUnless(os.getenv('RUN_PROMOTION_DB_TESTS')=='1','isolated PostgreSQL required')
class OverviewDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncpg
        self.conn=await asyncpg.connect(os.environ['DATABASE_URL'])
        await self.conn.execute('CREATE TEMP TABLE user_events(user_id TEXT,event_name TEXT,created_at TIMESTAMPTZ,properties JSONB DEFAULT \'{}\')')
        await self.conn.execute("CREATE TEMP TABLE restaurant_events(user_hash TEXT,event_name TEXT,created_at TIMESTAMPTZ,properties JSONB DEFAULT '{}')")
        conn=self.conn
        class Pool:
            def acquire(self):return self
            async def __aenter__(self):return conn
            async def __aexit__(self,*args):pass
        self.pool_patch=patch.object(insights_overview,'get_pool',return_value=Pool());self.pool_patch.start()

    async def asyncTearDown(self):self.pool_patch.stop();await self.conn.close()

    async def test_comparison_excludes_later_hours_and_qa_and_deduplicates_users(self):
        for user,day,hour in [('synthetic-current',21,'14:29'),('synthetic-current',21,'14:28'),
                              ('synthetic-late',21,'14:31'),('synthetic-prior',14,'14:29'),
                              ('synthetic-prior-late',14,'14:31'),('synthetic-qa',21,'14:20')]:
            await self.conn.execute("INSERT INTO user_events VALUES($1,'menu_view',$2::text::timestamptz,'{}')",user,f'2026-10-{day} {hour}+09')
        original=insights_overview.bounds
        now=datetime(2026,10,21,14,30,tzinfo=insights_overview.KST)
        with patch.object(insights_overview,'bounds',side_effect=lambda s,e:original(s,e,now)),patch.dict(os.environ,{'EXPERIMENT_QA_IDS':'synthetic-qa'}):
            result=await insights_overview.summary(date(2026,10,15),date(2026,10,21))
        self.assertEqual(result['current']['menu_users'],1)
        self.assertEqual(result['current']['menu_views'],2)
        self.assertEqual(result['previous']['menu_users'],1)
        self.assertEqual(result['daily'][0]['menu_users'],1)
        self.assertEqual(sum(r['events'] for r in result['activity']),2)
