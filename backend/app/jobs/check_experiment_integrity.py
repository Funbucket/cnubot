"""Read-only deployment check against frozen experiment policies and expected states."""
import argparse
import asyncio
import json
import os

import asyncpg
from app.services.experiment_lab import policy_checksum


async def check(args):
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    try:
        labs = await conn.fetch('SELECT id,status,protocol FROM lab_experiments')
        buttons = await conn.fetch('SELECT experiment_key,status FROM experiments')
        failures = []
        current = policy_checksum()
        for row in labs:
            if row['status'] in {'running', 'paused', 'observing'}:
                protocol = json.loads(row['protocol']) if isinstance(row['protocol'], str) else row['protocol']
                if protocol.get('policy_checksum') != current:
                    failures.append(f"lab #{row['id']}: frozen policy mismatch")
        lab_states = {row['id']: row['status'] for row in labs}
        button_states = {row['experiment_key']: row['status'] for row in buttons}
        for eid in args.expect_lab_id:
            if lab_states.get(eid) != 'running':
                failures.append(f'lab #{eid}: expected running')
        for key in args.expect_button_key:
            if button_states.get(key) != 'running':
                failures.append('button experiment: expected running')
        print('Experiment integrity:', 'FAILED' if failures else 'passed')
        for failure in failures:
            print(failure)
        return 1 if failures else 0
    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-lab-id', type=int, action='append', default=[])
    parser.add_argument('--expect-button-key', action='append', default=[])
    args = parser.parse_args()
    return asyncio.run(check(args))


if __name__ == '__main__':
    raise SystemExit(main())
