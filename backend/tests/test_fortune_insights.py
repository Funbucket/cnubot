"""Read private profile fields without depending on fortune calculation packages."""
import json
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from cryptography.fernet import Fernet

from app.services import fortune_insights


class PrivateProfileReportTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_profile_exposes_only_supported_summary_fields(self):
        key = Fernet.generate_key()
        payload = Fernet(key).encrypt(json.dumps({'input': {
            'birth_year': 2000, 'sex': 'female', 'birthplace': 'seoul',
            'birth_month': 12, 'birth_day': 31, 'birth_time': '12:34',
        }}).encode())
        connection = AsyncMock()
        connection.fetch.return_value = [{'created_at': datetime(2026, 1, 1, tzinfo=timezone.utc), 'payload': payload}]
        with patch.dict(os.environ, {'FORTUNE_ENCRYPTION_KEY': key.decode()}):
            result = await fortune_insights.recent_users(connection, None, None, [])
        self.assertEqual(result, [{'last_view_at': '01/01 09:00:00', 'birth_year': '2000년생',
                                   'sex': '여성', 'birthplace': '서울'}])

    async def test_unavailable_or_wrong_key_keeps_metrics_readable(self):
        payload = Fernet(Fernet.generate_key()).encrypt(b'{"input":{"birth_year":2000}}')
        connection = AsyncMock()
        connection.fetch.return_value = [{'created_at': datetime(2026, 1, 1, tzinfo=timezone.utc), 'payload': payload}]
        for key in ('', Fernet.generate_key().decode()):
            with self.subTest(key_configured=bool(key)), patch.dict(os.environ, {'FORTUNE_ENCRYPTION_KEY': key}):
                result = await fortune_insights.recent_users(connection, None, None, [])
                self.assertEqual(result[0], {'last_view_at': '01/01 09:00:00', 'birth_year': '—',
                                             'sex': '—', 'birthplace': '—'})
