import contextlib
import io
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.jobs import check_experiment_integrity as subject


class ExperimentIntegrityTest(unittest.IsolatedAsyncioTestCase):
    async def test_fails_on_changed_policy_or_missing_running_experiment(self):
        cases = [('running', 'frozen', 'running', 0),
                 ('running', 'changed', 'running', 1),
                 ('stopped', 'frozen', 'running', 1),
                 ('running', 'frozen', 'paused', 1)]
        for status, checksum, button_status, expected in cases:
            with self.subTest(status=status, checksum=checksum, button_status=button_status):
                conn = SimpleNamespace(fetch=AsyncMock(side_effect=[
                    [{'id': 2, 'status': status, 'protocol': {'policy_checksum': checksum}}],
                    [{'experiment_key': 'synthetic-button', 'status': button_status}]]), close=AsyncMock())
                args = SimpleNamespace(expect_lab_id=[2], expect_button_key=['synthetic-button'])
                with patch.dict(os.environ, DATABASE_URL='postgresql://example.invalid/test'), \
                     patch.object(subject.asyncpg, 'connect', AsyncMock(return_value=conn)), \
                     patch.object(subject, 'policy_checksum', return_value='frozen'), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(await subject.check(args), expected)
                conn.close.assert_awaited_once()
