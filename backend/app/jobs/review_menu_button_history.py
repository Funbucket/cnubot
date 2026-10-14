"""Read-only, aggregate-only feasibility review for the rendered menu entry button."""
import argparse
import asyncio
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import asyncpg

SQL = """
WITH e AS (
 SELECT user_id,created_at,properties FROM user_events
 WHERE created_at >= $1 AND created_at < $2
 AND event_name='promotion_entry_exposure' AND source='menu_button'
 AND properties->>'button_id'='toss_promotion_menu_button'
 AND user_id IS NOT NULL AND user_id<>'' AND NOT(user_id=ANY($3::text[]))
 AND COALESCE(properties->>'is_preview','false')<>'true'
), matched AS (
 SELECT DISTINCT u.user_id FROM user_events u
 WHERE u.created_at >= $1 AND u.created_at < $2
 AND u.event_name='promotion_entry_click' AND u.source='menu_button'
 AND u.properties->>'entry_button_id'='toss_promotion_menu_button'
 AND COALESCE(u.properties->>'is_preview','false')<>'true'
 AND EXISTS(SELECT 1 FROM e WHERE e.user_id=u.user_id AND e.created_at<=u.created_at
   AND e.properties->>'button_label'=u.properties->>'entry_button_label'
)
)
SELECT COUNT(DISTINCT e.user_id)::int AS users,COUNT(*)::int AS exposures,
 (SELECT COUNT(*)::int FROM matched) AS proxy_clicked,
 COUNT(*) FILTER (WHERE properties->>'collection_id' IS NULL)::int AS missing_exposure_collection FROM e
"""


async def review(end):
    if end > datetime.now(ZoneInfo('Asia/Seoul')).replace(hour=0, minute=0, second=0, microsecond=0):
        raise ValueError('Use a completed KST day as the exclusive end')
    excluded = [v.strip() for v in os.getenv('EXPERIMENT_QA_IDS', '').split(',') if v.strip()]
    excluded.append(os.getenv('DEVELOPER_ID', '').strip())
    conn = await asyncpg.connect(os.environ['DATABASE_URL'])
    try:
        async with conn.transaction(isolation='repeatable_read', readonly=True):
            for days, offset in [(7, 0), (14, 0), (28, 0), (7, 7), (7, 14), (7, 21)]:
                stop = end-timedelta(days=offset)
                start = stop-timedelta(days=days)
                row = dict(await conn.fetchrow(SQL, start, stop, excluded))
                print(json.dumps({'start_inclusive': start.isoformat(), 'end_exclusive': stop.isoformat(),
                                  **row, 'proxy_cumulative_user_ctr': row['proxy_clicked']/row['users'] if row['users'] else None}))
    finally:
        await conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--end', required=True, help='Exclusive KST date YYYY-MM-DD')
    args = parser.parse_args()
    asyncio.run(review(datetime.strptime(args.end, '%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Seoul'))))
