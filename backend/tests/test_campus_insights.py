"""Collection failure isolation, KST aggregates, hashed exclusions and report navigation."""
import hashlib
import json
import os
from pathlib import Path
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import FastAPI

from app.routers import shuttle as shuttle_router, insights_api, restaurants as restaurant_router
from app import database
from app.services import experiments, restaurant_catalog
from app.services import campus_insights, insights_overview, insights_cache, restaurants, shuttle


class ShuttleCollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_kakao_identity_status_and_analytics_failure(self):
        app = FastAPI()
        app.include_router(shuttle_router.router, prefix='/shuttle')
        data = {'bus_schedule': {'교내 순환': {'times': ['08:30', '09:00']}}, 'events': []}
        now = datetime(2026, 10, 22, 8, 40, tzinfo=insights_overview.KST)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://example.com') as client:
            with patch.object(shuttle_router.common, 'load_data', AsyncMock(return_value=data)), \
                 patch.object(shuttle.common, 'get_current_kr_time', return_value=now), \
                 patch.object(shuttle_router.experiments, 'record_funnel_event', AsyncMock()) as record:
                for user in [{'id': 'synthetic-user'}, None]:
                    response = await client.post('/shuttle/nearby', json={'userRequest': {'utterance': '셔틀', 'user': user}})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(record.await_args.args[:2], (user['id'] if user else None, 'shuttle_view'))
                    props = record.await_args.kwargs['properties']
                    self.assertEqual(props['status'], 'operating')
                    self.assertNotIn('utterance', props)
                    self.assertEqual(props['routes'], [{'route': '교내 순환', 'status': 'operating'}])
                record.side_effect = RuntimeError('synthetic failure')
                failed = await client.post('/shuttle/nearby', json={'userRequest': {'utterance': '셔틀'}})
                self.assertEqual(failed.json(), response.json())
                self.assertEqual((await client.post('/shuttle/nearby', json={})).status_code, 422)

    async def test_response_metadata_for_closed_before_first_and_ended(self):
        data = {'bus_schedule': {'교내 순환': {'times': ['08:30', '09:00']}}}
        for day, hour, expected in [(22, 7, 'before_first'), (22, 23, 'ended'), (24, 10, 'closed')]:
            with patch.object(shuttle.common, 'get_current_kr_time', return_value=datetime(2026, 10, day, hour, tzinfo=insights_overview.KST)):
                props = {}
                response = shuttle.create_nearby_shuttles_response(data, analytics=props)
                self.assertEqual(props['status'], expected)
                self.assertEqual(response, shuttle.create_nearby_shuttles_response(data))


class CampusReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_auth_dates_cache_and_refresh(self):
        app = FastAPI()
        app.include_router(insights_api.router, prefix='/admin')
        insights_cache._values.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://example.com') as client:
            with patch.dict(os.environ, {'ADMIN_USERNAME': 'synthetic', 'ADMIN_PASSWORD': 'synthetic-password'}), \
                 patch.object(campus_insights, 'summary', AsyncMock(return_value={})) as query:
                auth = ('synthetic', 'synthetic-password')
                for service in ['restaurants', 'shuttle']:
                    url = f'/admin/insights/api/{service}?start_date=2026-10-01&end_date=2026-10-22'
                    self.assertEqual((await client.get(url)).status_code, 401)
                    page = await client.get(url, auth=auth)
                    self.assertEqual(page.status_code, 200)
                    self.assertIn('no-store', page.headers['cache-control'])
                    query.assert_awaited_with(service, date(2026, 10, 1), date(2026, 10, 22))
                    count = query.await_count
                    await client.get(url, auth=auth)
                    self.assertEqual(query.await_count, count)
                    await client.get(url + '&refresh=true', auth=auth)
                    self.assertEqual(query.await_count, count + 1)
                    bad = await client.get(f'/admin/insights/api/{service}?start_date=2026-10-22&end_date=2026-10-01', auth=auth)
                    self.assertEqual(bad.status_code, 400)
                    self.assertEqual(query.await_count, count + 1)



@unittest.skipUnless(os.getenv('RUN_PROMOTION_DB_TESTS') == '1', 'isolated PostgreSQL required')
class CampusDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import asyncpg
        self.conn = await asyncpg.connect(os.environ['DATABASE_URL'])
        await self.conn.execute("""CREATE TEMP TABLE restaurant_events (
            event_id TEXT UNIQUE,user_hash TEXT,event_name TEXT,created_at TIMESTAMPTZ,properties JSONB DEFAULT '{}');
            CREATE TEMP TABLE user_events(user_id TEXT,event_name TEXT,created_at TIMESTAMPTZ,properties JSONB DEFAULT '{}');""")
        await self.conn.execute("CREATE TEMP TABLE restaurant_browse_states(user_hash TEXT PRIMARY KEY,state JSONB,updated_at TIMESTAMPTZ)")
        conn = self.conn
        class Pool:
            async def execute(self, *args): return await conn.execute(*args)
            def acquire(self): return self
            async def __aenter__(self): return conn
            async def __aexit__(self, *args): pass
        self.patches = [patch.object(module, 'get_pool', return_value=Pool()) for module in [campus_insights, insights_overview, database, experiments]]
        for p in self.patches: p.start()
        self.env = patch.dict(os.environ, {'EXPERIMENT_QA_IDS': 'synthetic-qa', 'DEVELOPER_ID': 'synthetic-dev'})
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        for p in self.patches: p.stop()
        await self.conn.close()

    async def restaurant_event(self, user, name, props=None, stamp='2026-10-22 00:30+09'):
        await self.conn.execute("INSERT INTO restaurant_events(user_hash,event_name,created_at,properties) VALUES($1,$2,$3::text::timestamptz,$4::jsonb)",
            hashlib.sha256(user.encode()).hexdigest() if user else None, name, stamp, json.dumps(props or {}))

    async def shuttle_event(self, user, status, stamp='2026-10-22 08:30+09'):
        await self.conn.execute("INSERT INTO user_events VALUES($1,'shuttle_view',$2::text::timestamptz,$3::jsonb)",
            user, stamp, json.dumps({'status': status, 'feature': 'shuttle', 'reason': '주말' if status == 'closed' else None}))

    async def test_restaurant_history_actions_refresh_empty_and_hash_exclusion(self):
        for user in ['synthetic-user', 'synthetic-qa', 'synthetic-dev']:
            await self.restaurant_event(user, 'entry')
            await self.restaurant_event(user, 'browse', {'action': 'area', 'area': '궁동'})
            await self.restaurant_event(user, 'recommendation', {'area': '궁동', 'budget': '1만원 미만', 'count': 1, 'place_ids': ['synthetic-place']})
            await self.restaurant_event(user, 'recommendation', {'area': '궁동', 'count': 0, 'place_ids': [], 'refresh': True})
            await self.restaurant_event(user, 'map_click', {'place_id': 'synthetic-place'})
        await self.restaurant_event('synthetic-history', 'recommendation', {'count': 1}, '2026-10-22 23:59:59+09')
        await self.restaurant_event('synthetic-next-day', 'entry', stamp='2026-10-23 00:00+09')
        result = await campus_insights.summary('restaurants', date(2026, 10, 22), date(2026, 10, 22))
        self.assertEqual(result['totals'], {'users': 2, 'views': 1, 'recommendations': 3, 'empty_results': 1, 'refreshes': 1, 'map_users': 1, 'map_clicks': 1})
        self.assertEqual(result['places'][0]['exposures'], 1)
        self.assertEqual(result['places'][0]['clicks'], 1)
        self.assertEqual(result['areas'][0], {'label': '궁동', 'users': 1, 'events': 2})
        self.assertEqual(result['actions'][0]['events'], 1)
        self.assertEqual(result['daily'][0]['day'], date(2026, 10, 22))
        self.assertEqual(sum(r['events'] for r in result['activity']), 1)
        self.assertNotIn('synthetic-user', json.dumps(result, default=str))

    async def test_shuttle_repeats_anonymous_status_and_overview_match(self):
        for user in ['synthetic-user', 'synthetic-qa', 'synthetic-dev']:
            await self.shuttle_event(user, 'operating')
            await self.shuttle_event(user, 'ended')
            await self.restaurant_event(user, 'entry', stamp='2026-10-22 08:30+09')
            await self.restaurant_event(user, 'browse', stamp='2026-10-22 08:30+09')
        await self.shuttle_event(None, 'closed')
        await self.shuttle_event('synthetic-prior', 'before_first', '2026-10-21 08:30+09')
        result = await campus_insights.summary('shuttle', date(2026, 10, 22), date(2026, 10, 22))
        self.assertEqual(result['totals'], {'users': 1, 'views': 3, 'operating': 1, 'before_first': 0, 'ended': 1, 'closed': 1})
        self.assertEqual(sum(r['events'] for r in result['activity']), 3)
        original = insights_overview.bounds
        now = datetime(2026, 10, 22, 12, tzinfo=insights_overview.KST)
        with patch.object(insights_overview, 'bounds', side_effect=lambda s,e: original(s,e,now)):
            overview = await insights_overview.summary(date(2026, 10, 22), date(2026, 10, 22))
        self.assertEqual(overview['current']['shuttle_users'], 1)
        self.assertEqual(overview['current']['restaurant_users'], 1)
        self.assertEqual(overview['previous']['shuttle_users'], 1)
        self.assertEqual(overview['daily'][0]['shuttle_users'], 1)

    async def test_skill_request_to_database_to_authenticated_report(self):
        from app.schemas.restaurants import Catalog
        app = FastAPI()
        app.include_router(restaurant_router.router, prefix='/restaurants')
        app.include_router(shuttle_router.router, prefix='/shuttle')
        app.include_router(insights_api.router, prefix='/admin')
        # Add the real collector's columns only to these connection-local tables.
        await self.conn.execute("""ALTER TABLE restaurant_events ADD COLUMN session_id TEXT;
            ALTER TABLE restaurant_events ALTER COLUMN created_at SET DEFAULT NOW();
            ALTER TABLE user_events ADD COLUMN event_id TEXT, ADD COLUMN schema_version INT,
                ADD COLUMN source TEXT, ADD COLUMN surface TEXT, ADD COLUMN product_key TEXT,
                ADD COLUMN taca_item_id INT, ADD COLUMN request_id TEXT;
            ALTER TABLE user_events ALTER COLUMN created_at SET DEFAULT NOW();""")
        migration = (Path(__file__).parents[1] / 'app/migrations/005_restaurant_browse_events.sql').read_text()
        await self.conn.execute(migration)
        await self.conn.execute(migration)
        insights_cache._values.clear()
        with patch.dict(os.environ, {'ADMIN_USERNAME': 'synthetic', 'ADMIN_PASSWORD': 'synthetic-password'}), \
             patch.object(restaurant_catalog, 'safe_catalog', return_value=Catalog(items=[])), \
             patch.object(shuttle_router.common, 'load_data', AsyncMock(return_value={'bus_schedule': {'교내 순환': {'times': ['08:30', '09:00']}}})):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://example.com') as client:
                for route, message in [('home', restaurants.HOME), ('area', '주변맛집 궁동'), ('budget', '주변맛집 궁동 1만원 미만'), ('more', restaurants.MORE)]:
                    response = await client.post('/restaurants/' + route, json={'userRequest': {'utterance': message, 'user': {'id': 'synthetic-user'}}})
                    self.assertEqual(response.status_code, 200)
                response = await client.post('/shuttle/nearby', json={'userRequest': {'utterance': '셔틀', 'user': {'id': 'synthetic-user'}}})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(await self.conn.fetchval("SELECT COUNT(*) FROM restaurant_events WHERE event_name='browse'"), 4)
                self.assertEqual(await self.conn.fetchval("SELECT COUNT(*) FROM restaurant_events WHERE event_name='recommendation'"), 2)
                self.assertEqual(await self.conn.fetchval("SELECT COUNT(*) FROM user_events WHERE event_name='shuttle_view'"), 1)
                for service in ['restaurants', 'shuttle']:
                    report = await client.get('/admin/insights/api/' + service + '?all_time=true', auth=('synthetic', 'synthetic-password'))
                    self.assertEqual(report.status_code, 200)
                    self.assertEqual(report.json()['data']['totals']['users'], 1)
