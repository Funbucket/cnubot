"""Report access controls, lazy personal data, and encrypted transport boundaries."""
import asyncio
import base64
import json
import os
import secrets
import time
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import FastAPI

from app.routers import insights_api
from app.services import insights_cache, insights_data


class ReportAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.key = secrets.token_bytes(32)
        self.env = patch.dict(os.environ, {'ADMIN_USERNAME': 'synthetic', 'ADMIN_PASSWORD': 'synthetic-password',
                                          'INSIGHTS_RELAY_KEY': base64.urlsafe_b64encode(self.key).decode()})
        self.env.start()
        app = FastAPI()
        app.include_router(insights_api.router, prefix='/admin')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://example.com')
        self.query = AsyncMock(return_value={'report': 'overview', 'data': {'day': date(2026, 10, 23), 'missing': None}})
        self.loader = patch.object(insights_api, 'load_report', self.query)
        self.loader.start()

    async def asyncTearDown(self):
        await self.client.aclose()
        self.loader.stop()
        self.env.stop()

    def envelope(self, query=None, issued_at=None, direction='request'):
        request_id, nonce = str(uuid4()), secrets.token_bytes(12)
        body = json.dumps({'issued_at': int(time.time()) if issued_at is None else issued_at,
                           'query': query or {'report': 'overview'}}).encode()
        ciphertext = AESGCM(self.key).encrypt(nonce, body, insights_api.aad(direction, request_id))
        return {'version': 1, 'id': request_id, 'iv': base64.urlsafe_b64encode(nonce).decode().rstrip('='),
                'data': base64.urlsafe_b64encode(ciphertext).decode().rstrip('=')}

    async def test_all_json_reports_require_admin_even_personal_data(self):
        for report in ('overview', 'fortune', 'restaurants', 'shuttle', 'products', 'quality', 'revenue', 'fortune-users'):
            response = await self.client.get('/admin/insights/api/' + report)
            self.assertEqual(response.status_code, 401)
        self.query.assert_not_awaited()

    async def test_json_dates_nulls_and_no_store(self):
        response = await self.client.get('/admin/insights/api/overview', auth=('synthetic', 'synthetic-password'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], {'day': '2026-10-23', 'missing': None})
        self.assertIn('no-store', response.headers['cache-control'])

    async def test_invalid_periods_and_unknown_report_never_hit_database(self):
        for query in ('start_date=2026-10-23&end_date=2026-10-01', 'start_date=2026-02-30', 'all_time=true&start_date=2026-10-23'):
            response = await self.client.get('/admin/insights/api/overview?' + query, auth=('synthetic', 'synthetic-password'))
            self.assertIn(response.status_code, (400, 422))
        response = await self.client.get('/admin/insights/api/arbitrary', auth=('synthetic', 'synthetic-password'))
        self.assertEqual(response.status_code, 422)
        self.query.assert_not_awaited()

    async def test_encrypted_roundtrip_contains_no_plaintext_report(self):
        envelope = self.envelope()
        response = await self.client.post('/admin/insights/relay', json=envelope)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('2026-10-23', response.text)
        value = response.json()
        plaintext = AESGCM(self.key).decrypt(insights_api.decode(value['iv'], 16), insights_api.decode(value['data'], 10000), insights_api.aad('response', envelope['id']))
        result = json.loads(plaintext)
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['body']['data']['day'], '2026-10-23')
        self.assertIn('no-store', response.headers['cache-control'])

    async def test_invalid_expired_reflected_and_tampered_requests_are_denied(self):
        tampered = self.envelope()
        data = bytearray(insights_api.decode(tampered['data'], 6000)); data[0] ^= 1
        tampered['data'] = base64.urlsafe_b64encode(data).decode().rstrip('=')
        envelopes = [self.envelope(issued_at=int(time.time()) - 91), self.envelope(issued_at=int(time.time()) + 31),
                     self.envelope(direction='response'), self.envelope({'report': 'arbitrary'}), tampered, {},
                     {**self.envelope(), 'extra': 'forbidden'}]
        for envelope in envelopes:
            response = await self.client.post('/admin/insights/relay', json=envelope)
            self.assertEqual(response.status_code, 403)
        self.query.assert_not_awaited()

    async def test_oversized_request_does_not_execute_report(self):
        response = await self.client.post('/admin/insights/relay', content=b'x' * 8193)
        self.assertEqual(response.status_code, 413)
        self.query.assert_not_awaited()

    async def test_failure_is_generic_and_encrypted(self):
        self.query.side_effect = RuntimeError('synthetic-sensitive-details')
        response = await self.client.post('/admin/insights/relay', json=self.envelope())
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('synthetic-sensitive-details', response.text)
        response = await self.client.get('/admin/insights/api/overview', auth=('synthetic', 'synthetic-password'))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('synthetic-sensitive-details', response.text)
        self.assertIn('no-store', response.headers['cache-control'])


class ReportLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        insights_cache._values.clear()
        insights_cache._pending.clear()

    def test_default_period_is_recent_seven_kst_days(self):
        start, end = insights_data.ReportQuery(report='overview').dates()
        self.assertEqual((end - start).days, 6)
        self.assertEqual(insights_data.ReportQuery(report='overview', all_time=True).dates(), (None, None))

    async def test_fortune_aggregate_does_not_read_personal_data(self):
        with patch.object(insights_data.fortune_insights, 'summary', AsyncMock(return_value={'result_users': 1})) as load:
            result = await insights_data.load_report(insights_data.ReportQuery(report='fortune'))
        self.assertEqual(result['data'], {'result_users': 1})
        self.assertFalse(load.await_args.kwargs['include_recent'])

    async def test_products_and_quality_share_one_cached_aggregate(self):
        aggregate = {'totals': {'product_clicked_users': 1}, 'products': [], 'guardrails': [], 'positions': []}
        with patch.object(insights_data, 'get_pool', return_value=object()), patch.object(insights_data.promotion_insights, 'get_promotion_insights', AsyncMock(return_value=aggregate)) as load:
            products, quality = await asyncio.gather(*[insights_data.load_report(insights_data.ReportQuery(report=report)) for report in ('products', 'quality')])
        load.assert_awaited_once()
        self.assertNotIn('guardrails', products['data'])
        self.assertNotIn('products', quality['data'])

    async def test_personal_data_bypasses_aggregate_cache(self):
        class Pool:
            def acquire(self): return self
            async def __aenter__(self): return object()
            async def __aexit__(self, *args): pass
        with patch.object(insights_data, 'get_pool', return_value=Pool()), patch.object(insights_data.fortune_insights, 'recent_users', AsyncMock(return_value=[])) as load:
            for _ in range(2): await insights_data.load_report(insights_data.ReportQuery(report='fortune-users'))
        self.assertEqual(load.await_count, 2)
        self.assertFalse(insights_cache._values)
