"""Apply the documented, post-start feasibility amendment once; preserve assignments."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import asyncpg
from app.services.menu_button_experiment import KEY

REVISION = 'historical-feasibility-2026-10-14'


async def main():
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    try:
        async with conn.transaction():
            row = await conn.fetchrow('SELECT * FROM experiments WHERE experiment_key=$1 FOR UPDATE', KEY)
            if not row or row['status'] != 'running':
                raise ValueError('Expected the existing running button experiment')
            plan = json.loads(row['analysis_plan']) if isinstance(row['analysis_plan'], str) else row['analysis_plan']
            if plan.get('revision') == REVISION:
                print('Plan already amended; no changes')
                return
            deadline = row['started_at'] + timedelta(days=7)
            if datetime.now(timezone.utc) >= deadline:
                raise ValueError('Cannot amend an elapsed collection window')
            amended = {
                **plan, 'revision': REVISION, 'mode': 'exploratory_timebox',
                'amended_at': datetime.now(timezone.utc).isoformat(),
                'post_start_amendment': True,
                'reason': '실제 적격 순사용자 검토 없이 설정한 3534명 목표를 운영 계획에서 폐기',
                'original_plan': {k: row[k] for k in ('baseline_rate', 'mde', 'alpha', 'power', 'min_sample_size')},
                'original_analysis_plan': plan,
                'planned_total_users': 1200, 'expected_users_range': [800, 1600],
                'deadline': deadline.isoformat(), 'duration_days': 7,
                'baseline_is_planning_assumption': False,
                'historical_proxy_rate': 55/1649,
                'historical_window': ['2026-10-07T00:00:00+09:00', '2026-10-14T00:00:00+09:00'],
                'historical_users': {'7d': 1649, '14d': 1847, '28d': 2017},
                'baseline_limit': '과거 노출 기획전 ID 누락; 문구+선행 노출 기반 55/1649는 참고율, 엄격한 지표와 동일하지 않음',
                'decision': '7일 고정 종료; 예상 1200명은 검정력 보장/조기 종료 기준 아님. 사후 개정 탐색 결과만 보고하고 자동 승자 없음. 목표 미달/CI 불확실 시 판단 보류. 유의성에 따른 연장 금지.',
                'analysis_method': 'two-sided Fisher exact; Newcombe-Wilson 95% CI; endpoint cumulative user CTR',
                'effect_scenarios_pp': [1, 2, 2.5, 3],
                'power_at_1200_proxy': [0.1176, 0.3508, 0.4984, 0.6411],
                'power_at_1600_proxy': [0.1482, 0.4556, 0.6280, 0.7727],
                'concurrent_inline_test': '기존 학식 저가 먹거리 24시간 탐색 A/B 유지; 독립 배정; 상호작용 미검증',
                'review_document': 'docs/menu-button-experiment-design.md',
            }
            await conn.execute('UPDATE experiments SET analysis_plan=$2::jsonb WHERE id=$1', row['id'], json.dumps(amended, ensure_ascii=False))
            print(json.dumps({'amended': True, 'planned_total_users': 1200, 'deadline': deadline.isoformat(), 'preserved_original_plan_and_assignments': True}))
    finally:
        await conn.close()


if __name__ == '__main__':
    asyncio.run(main())
