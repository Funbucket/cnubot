import json
import os
import unittest
import uuid
from unittest.mock import patch

import asyncpg
from app.services import experiments


class TimeboxQualityTest(unittest.TestCase):
    def test_exploration_never_becomes_automatic_winner(self):
        row = {'min_sample_size': 10, 'alpha': .05, 'power': .8,
               'analysis_plan': json.dumps({'mode': 'exploratory_timebox', 'planned_total_users': 1200})}
        variants = [{'exposed_users': 100, 'comparison': {'p_value': .001}}]
        result = experiments._quality_summary(row, variants, {'status': 'pass'})
        self.assertTrue(result['sample_size_ok'])
        self.assertFalse(result['decision_ready'])
        self.assertEqual(result['planned_total_users'], 1200)


@unittest.skipUnless(os.getenv('LAB_TEST_DATABASE_URL'), 'isolated DB required')
class TimeboxDatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.schema = 'test_button_' + uuid.uuid4().hex
        self.root = await asyncpg.connect(os.environ['LAB_TEST_DATABASE_URL'])
        await self.root.execute(f'CREATE SCHEMA {self.schema}')
        self.pool = await asyncpg.create_pool(os.environ['LAB_TEST_DATABASE_URL'], min_size=1, max_size=2,
                                             server_settings={'search_path': self.schema})
        await self.pool.execute('''CREATE TABLE experiments (
            id serial PRIMARY KEY, experiment_key text, primary_metric text,
            status text, analysis_plan jsonb, ended_at timestamptz);
            CREATE TABLE experiment_assignments(experiment_id int,user_id text,variant_key text);
            CREATE TABLE lab_experiments(id int,status text);''')
        self.patcher = patch.object(experiments, 'get_pool', return_value=self.pool)
        self.patcher.start()

    async def asyncTearDown(self):
        self.patcher.stop()
        await self.pool.close()
        await self.root.execute(f'DROP SCHEMA {self.schema} CASCADE')
        await self.root.close()

    async def test_deadline_blocks_events_and_enrollment_and_preserves_other_tests(self):
        await self.pool.execute('''INSERT INTO experiments(experiment_key,primary_metric,status,analysis_plan)
          VALUES ('expired','menu_button_entry_ctr','running',
                  jsonb_build_object('mode','exploratory_timebox','deadline',NOW()-INTERVAL '1 day')),
                 ('future','menu_button_entry_ctr','running',
                  jsonb_build_object('mode','exploratory_timebox','deadline',NOW()+INTERVAL '1 day')),
                 ('legacy','menu_button_entry_ctr','running','{}');
          INSERT INTO experiment_assignments VALUES(1,'synthetic','control');
          INSERT INTO lab_experiments VALUES(2,'running');''')
        self.assertIsNone(await experiments.get_active_variant('expired', 'new-synthetic'))
        # No user_events table: an attempted late write would fail this test.
        await experiments.record_event('expired','synthetic','menu_button_click')
        await experiments.complete_due_timeboxes()
        await experiments.complete_due_timeboxes()
        states = {r['experiment_key']: r['status'] for r in await self.pool.fetch('SELECT * FROM experiments')}
        self.assertEqual(states, {'expired': 'completed', 'future': 'running', 'legacy': 'running'})
        self.assertEqual(await self.pool.fetchval('SELECT COUNT(*) FROM experiment_assignments'), 1)
        self.assertEqual(await self.pool.fetchval('SELECT status FROM lab_experiments'), 'running')
        self.assertTrue(await self.pool.fetchval("SELECT ended_at=(analysis_plan->>'deadline')::timestamptz FROM experiments WHERE id=1"))
        with self.assertRaisesRegex(ValueError,'마감'):
            await experiments.set_experiment_status(1,'running')
