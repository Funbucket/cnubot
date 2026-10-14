import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from app.app import app
from app.services import experiments


class AdminButtonExperimentsTest(unittest.TestCase):
    def test_detail_and_status_routes_keep_experiment_namespaces_separate(self):
        rows = [{"id": 5, "name": "버튼 A/B", "status": "running", "started_at": None,
                 "primary_metric": "menu_button_entry_ctr", "variants": []},
                {"id": 1, "primary_metric": "promotion_click_rate"}]
        with patch.dict(os.environ, ADMIN_USERNAME="test-admin", ADMIN_PASSWORD="test-password"), \
             patch.object(experiments, "list_experiments", AsyncMock(return_value=rows)), \
             patch.object(experiments, "get_analysis", AsyncMock(side_effect=RuntimeError("unavailable"))), \
             patch.object(experiments, "set_experiment_status", new_callable=AsyncMock) as change:
            client = TestClient(app)
            auth = ("test-admin", "test-password")
            self.assertEqual(client.get('/admin/api/button-experiments/5', auth=auth).json()['id'], 5)
            self.assertEqual(client.get('/admin/api/button-experiments/1', auth=auth).status_code, 404)
            self.assertEqual(client.post('/admin/api/button-experiments/5/paused', auth=auth).status_code, 403)
            headers = {'X-Experiment-Admin': '1'}
            self.assertEqual(client.post('/admin/api/button-experiments/1/paused', auth=auth, headers=headers).status_code, 404)
            change.assert_not_awaited()
            self.assertEqual(client.post('/admin/api/button-experiments/5/paused', auth=auth, headers=headers).status_code, 200)
            change.assert_awaited_once_with(5, 'paused')
            rows[0]['status'] = 'completed'
            self.assertEqual(client.post('/admin/api/button-experiments/5/running', auth=auth, headers=headers).status_code, 400)

    def test_auth_filter_and_partial_analysis_failure(self):
        rows = [{"id": 5, "name": "버튼 A/B", "status": "running", "started_at": None,
                 "primary_metric": "menu_button_entry_ctr", "created_by": "private-actor",
                 "variants": [{"variant_key": "control", "label": "먹거리", "weight": 50,
                               "config": {"private": "hidden"}}]},
                {"id": 1, "primary_metric": "promotion_click_rate"}]
        with patch.dict(os.environ, ADMIN_USERNAME="test-admin", ADMIN_PASSWORD="test-password"), \
             patch.object(experiments, "list_experiments", AsyncMock(return_value=rows)), \
             patch.object(experiments, "get_analysis", AsyncMock(side_effect=RuntimeError("unavailable"))) as analyze:
            client = TestClient(app)  # Skip lifespan and production database initialization.
            self.assertEqual(client.get('/admin/api/button-experiments').status_code, 401)
            response = client.get('/admin/api/button-experiments', auth=("test-admin", "test-password"))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers['cache-control'], 'no-store')
            data = response.json()
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]['status'], 'running')
            self.assertIsNone(data[0]['analysis'])
            self.assertNotIn('created_by', data[0])
            self.assertNotIn('config', data[0]['variants'][0])
            analyze.assert_awaited_once_with(5)

    def test_live_counts_are_returned(self):
        row = {"id": 5, "name": "버튼 A/B", "status": "running", "started_at": None,
               "primary_metric": "menu_button_entry_ctr", "variants": []}
        analysis = {"variants": [{"variant_key": "control", "exposed_users": 10, "clicked_users": 1}],
                    "min_sample_size_per_variant": 1767, "srm": {"status": "pass"}, "quality": {}}
        with patch.dict(os.environ, ADMIN_USERNAME="test-admin", ADMIN_PASSWORD="test-password"), \
             patch.object(experiments, "list_experiments", AsyncMock(return_value=[row])), \
             patch.object(experiments, "get_analysis", AsyncMock(return_value=analysis)):
            client = TestClient(app)
            response = client.get('/admin/api/button-experiments', auth=("test-admin", "test-password"))
            self.assertEqual(response.json()[0]['analysis']['variants'][0]['exposed_users'], 10)
