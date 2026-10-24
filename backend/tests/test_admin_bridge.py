"""Security and dispatch checks using synthetic handlers; never operational writes."""
import base64
import json
import os
import secrets
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import httpx
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, FastAPI, Header, HTTPException

from app.routers import admin_bridge as bridge
from app.routers.admin import require_admin


class AdminBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.key = secrets.token_bytes(32)
        self.env = patch.dict(os.environ, dict(ADMIN_USERNAME='synthetic', ADMIN_PASSWORD='synthetic-password',
            INSIGHTS_RELAY_KEY=base64.urlsafe_b64encode(self.key).decode(), MENU_DATA_DIR=self.directory.name))
        self.env.start()
        self.effects = []
        app = FastAPI()
        app.include_router(bridge.router, prefix='/admin')

        @app.get('/admin/promotion-settings', dependencies=[Depends(require_admin)])
        async def settings():
            return {'revision': 12, 'label': 'synthetic private setting'}

        @app.put('/admin/promotion-settings', dependencies=[Depends(require_admin)])
        async def save(body: dict, x_promotion_editor: str = Header(default='')):
            if x_promotion_editor != '1':
                raise HTTPException(403, 'Editor header required')
            self.effects.append(body)
            return {'revision': 13}

        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://example.com')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.env.stop()
        self.directory.cleanup()

    def envelope(self, **overrides):
        purpose = overrides.pop('purpose', 'admin-bridge')
        request_id, nonce = str(uuid4()), secrets.token_bytes(12)
        message = dict(issued_at=int(time.time()), method='GET', path='/admin/promotion-settings', query='', body='',
                       username='synthetic', password='synthetic-password', headers={})
        message.update(overrides)
        data = AESGCM(self.key).encrypt(nonce, json.dumps(message).encode(), f'{purpose}:v1:request:{request_id}'.encode())
        encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
        return dict(version=1, id=request_id, iv=encode(nonce), data=encode(data))

    async def send(self, envelope):
        response = await self.client.post('/admin/workspace/relay', json=envelope)
        self.assertIn('no-store', response.headers['cache-control'])
        if response.status_code != 200:
            return response.status_code, None
        payload = response.json()
        data = AESGCM(self.key).decrypt(bridge.decode(payload['iv'], 16), bridge.decode(payload['data'], 2_000_000), bridge.aad('response', envelope['id']))
        return response.status_code, json.loads(data)

    async def test_authenticated_read_is_encrypted_and_preserves_content_type(self):
        envelope = self.envelope()
        response = await self.client.post('/admin/workspace/relay', json=envelope)
        self.assertNotIn('synthetic private setting', response.text)
        _, payload = await self.send(envelope)
        self.assertEqual(payload['status'], 200)
        self.assertEqual(json.loads(payload['body'])['revision'], 12)
        self.assertEqual(payload['content_type'], 'application/json')

    async def test_relay_key_does_not_authorize_admin_operations_without_admin_credentials(self):
        for method in ['GET', 'PUT']:
            _, payload = await self.send(self.envelope(method=method, password='wrong', body='' if method == 'GET' else '{}', headers={'x-promotion-editor': '1'}))
            self.assertEqual(payload['status'], 401)
        self.assertEqual(self.effects, [])

    async def test_editor_guard_and_atomic_persistent_write_replay_protection(self):
        _, guarded = await self.send(self.envelope(method='PUT', body='{}'))
        self.assertEqual(guarded['status'], 403)
        envelope = self.envelope(method='PUT', body='{"mode":"synthetic"}', headers={'x-promotion-editor': '1'})
        _, first = await self.send(envelope)
        _, replay = await self.send(envelope)
        self.assertEqual(first['status'], 200)
        self.assertEqual(replay['status'], 409)
        self.assertEqual(self.effects, [{'mode': 'synthetic'}])
        self.assertFalse(bridge.claim_write(envelope['id']))

    async def test_invalid_destinations_headers_expiry_and_report_ciphertexts_never_dispatch(self):
        invalid = [dict(path='https://example.com/admin/promotion-settings'), dict(path='/admin/../admin/promotion-settings'),
            dict(path='/admin/experiments'), dict(path='/admin/events'), dict(path='/admin/assets/admin_nav.css'),
            dict(path='/admin/%70romotion-settings'), dict(path='/admin/workspace/relay'), dict(path='/admin/api/experiments/3/running', method='POST'),
            dict(path='/admin/api/button-experiments/3/enrollment', method='POST'), dict(headers={'authorization': 'forbidden'}),
            dict(headers={'x-promotion-editor': '0'}), dict(issued_at=int(time.time()) - 91), dict(issued_at=int(time.time()) + 31),
            dict(query='x=1\r\nInjected: true'), dict(body='{}'), dict(purpose='insights-relay')]
        for overrides in invalid:
            status, _ = await self.send(self.envelope(**overrides))
            self.assertEqual(status, 403, str(overrides))
        self.assertEqual(self.effects, [])

    async def test_tampered_and_oversized_envelopes_are_rejected(self):
        value = self.envelope()
        data = bytearray(bridge.decode(value['data'], bridge.MAX_BODY)); data[0] ^= 1
        value['data'] = base64.urlsafe_b64encode(data).decode().rstrip('=')
        status, _ = await self.send(value)
        self.assertEqual(status, 403)
        response = await self.client.post('/admin/workspace/relay', content=b'x' * (bridge.MAX_BODY + 1))
        self.assertEqual(response.status_code, 413)

    async def test_only_explicit_existing_admin_routes_are_exposed(self):
        for method, path in [('POST', '/admin/api/button-experiments/3/paused'), ('PUT', '/admin/api/experiments/3'),
            ('GET', '/admin/api/experiments/3/results'), ('DELETE', '/admin/api/experiments/3/preview-override')]:
            self.assertTrue(bridge.allowed(method, path))
        for path in ['/fortune', '/admin/experiments/legacy', '/admin/api/experiments/0/results', '/admin/promotion-settings/preview/']:
            self.assertFalse(bridge.allowed('GET', path))
