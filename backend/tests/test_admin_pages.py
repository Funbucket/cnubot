"""Retired UI bookmarks redirect safely; operational APIs keep their own auth."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi import FastAPI

from app.routers import admin_pages


class AdminPageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, dict(ADMIN_USERNAME='synthetic', ADMIN_PASSWORD='synthetic-password',
            ADMIN_WEB_ORIGIN='https://admin.example.com', MENU_DATA_DIR=self.directory.name))
        self.env.start()
        app = FastAPI()
        app.include_router(admin_pages.router, prefix='/admin')
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://example.com')
        self.auth = ('synthetic', 'synthetic-password')

    async def asyncTearDown(self):
        await self.client.aclose()
        self.env.stop()
        self.directory.cleanup()

    async def test_old_pages_require_auth_and_redirect_to_the_fixed_frontend(self):
        for source, destination in admin_pages.PAGES.items():
            self.assertEqual((await self.client.get('/admin' + source)).status_code, 401)
            response = await self.client.get('/admin' + source, auth=self.auth)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], 'https://admin.example.com' + destination)
            self.assertIn('no-store', response.headers['cache-control'])
            self.assertNotIn('<html', response.text.lower())

    async def test_queries_and_host_cannot_change_destination_or_forward_credentials(self):
        response = await self.client.get('/admin/insights/products?start_date=2026-01-01&end_date=2026-01-07&next=https://other.example.com&password=private', auth=self.auth,
                                         headers={'host': 'other.example.com'})
        self.assertEqual(response.headers['location'], 'https://admin.example.com/insights/products?start_date=2026-01-01&end_date=2026-01-07')
        self.assertNotIn('private', response.headers['location'])

    async def test_missing_or_invalid_origin_fails_without_redirecting(self):
        for origin in ['', 'https://user:secret@example.com', 'https://example.com/path', 'https://example.com?next=x', 'javascript:example.com', 'https://example.com/#x']:
            with patch.dict(os.environ, {'ADMIN_WEB_ORIGIN': origin}):
                response = await self.client.get('/admin/experiments', auth=self.auth)
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('location', response.headers)

    async def test_private_persistent_configuration_supports_existing_container(self):
        Path(self.directory.name, '.admin-web-origin').write_text('https://admin.example.com/')
        with patch.dict(os.environ, {'ADMIN_WEB_ORIGIN': ''}):
            response = await self.client.get('/admin/experiments', auth=self.auth)
        self.assertEqual(response.headers['location'], 'https://admin.example.com/admin/experiments')
