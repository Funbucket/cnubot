"""Small, independent overview aggregates; no funnel qualification or profile decryption."""
import os
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.database import get_pool

KST = ZoneInfo('Asia/Seoul')
CLICKS = ('promotion_click', 'promotion_button_click', 'promotion_quick_reply_click',
          'promotion_block_click', 'commerce_card_click')


def excluded_users():
    return sorted({s.strip() for s in os.getenv('EXPERIMENT_QA_IDS', '').split(',') if s.strip()}
                  | ({os.environ['DEVELOPER_ID'].strip()} if os.getenv('DEVELOPER_ID', '').strip() else set()))


def bounds(start, end, now=None):
    now = now or datetime.now(KST)
    finish = min(datetime.combine(end, time.max, KST) + timedelta(microseconds=1), now) if end and end.year < 9999 else now
    begin = datetime.combine(start, time.min, KST) if start else None
    previous_begin = previous_finish = None
    if begin and begin < finish:
        # Compare equal elapsed portions when today is still collecting.
        last = min(end or now.date(), now.date())
        days = (last - start).days + 1
        if start.toordinal() > days:
            previous_begin = begin - timedelta(days=days)
            previous_finish = finish - timedelta(days=days)
    return begin, finish, previous_begin, previous_finish


async def summary(start=None, end=None):
    begin, finish, previous_begin, previous_finish = bounds(start, end)
    scan_begin = previous_begin or begin
    from app.services.campus_insights import overview_events, excluded_hashes
    excluded = excluded_users()
    restaurant_excluded = excluded_hashes()
    activity_events = ['menu_view', 'fortune_response_created', 'shuttle_view', 'restaurant_activity', *CLICKS]
    async with get_pool().acquire() as conn:
        counts = await conn.fetch(overview_events(8) + """
            SELECT CASE WHEN $1::timestamptz IS NULL OR created_at >= $1 THEN 'current' ELSE 'previous' END AS period,
                COUNT(DISTINCT user_id) FILTER(WHERE event_name='menu_view')::int AS menu_users,
                COUNT(*) FILTER(WHERE event_name='menu_view')::int AS menu_views,
                COUNT(DISTINCT user_id) FILTER(WHERE event_name=ANY($6::text[]))::int AS clicked_users,
                COUNT(*) FILTER(WHERE event_name=ANY($6::text[]))::int AS click_events,
                COUNT(DISTINCT user_id) FILTER(WHERE event_name='fortune_response_created' AND properties->>'feature'='fortune')::int AS fortune_users,
                COUNT(DISTINCT user_id) FILTER(WHERE event_name='shuttle_view')::int AS shuttle_users,
                COUNT(DISTINCT user_id) FILTER(WHERE event_name='restaurant_activity')::int AS restaurant_users
            FROM events
            WHERE ($2::timestamptz IS NULL OR created_at >= $2) AND created_at < $3
              AND (created_at >= $1 OR $1::timestamptz IS NULL OR created_at < $4)
              AND event_name=ANY($7::text[])
              AND (user_id IS NULL OR NOT(user_id=ANY($5::text[])))
            GROUP BY 1
        """, begin, scan_begin, finish, previous_finish, excluded, list(CLICKS), activity_events, restaurant_excluded)
        daily = await conn.fetch(overview_events(6) + """
            SELECT (created_at AT TIME ZONE 'Asia/Seoul')::date AS day,
                COUNT(DISTINCT user_id) FILTER(WHERE event_name='menu_view')::int AS menu_users,
                COUNT(DISTINCT user_id) FILTER(WHERE event_name=ANY($4::text[]))::int AS clicked_users,
                COUNT(DISTINCT user_id) FILTER(WHERE event_name='fortune_response_created' AND properties->>'feature'='fortune')::int AS fortune_users,
                CASE WHEN COUNT(*) FILTER(WHERE event_name='shuttle_view')>0 THEN COUNT(DISTINCT user_id) FILTER(WHERE event_name='shuttle_view')::int END AS shuttle_users,
                CASE WHEN COUNT(*) FILTER(WHERE event_name='restaurant_activity')>0 THEN COUNT(DISTINCT user_id) FILTER(WHERE event_name='restaurant_activity')::int END AS restaurant_users
            FROM events WHERE ($1::timestamptz IS NULL OR created_at >= $1) AND created_at < $2
                AND created_at >= $2 - INTERVAL '30 days'
                AND event_name=ANY($5::text[])
                AND (user_id IS NULL OR NOT(user_id=ANY($3::text[])))
            GROUP BY 1 ORDER BY 1
        """, begin, finish, excluded, list(CLICKS), activity_events, restaurant_excluded)
        activity = await conn.fetch("""
            SELECT EXTRACT(ISODOW FROM created_at AT TIME ZONE 'Asia/Seoul')::int AS weekday,
                EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Seoul')::int AS hour, COUNT(*)::int AS events
            FROM user_events WHERE event_name='menu_view'
              AND ($1::timestamptz IS NULL OR created_at >= $1) AND created_at < $2
              AND (user_id IS NULL OR NOT(user_id=ANY($3::text[])))
            GROUP BY 1,2
        """, begin, finish, excluded)
    values = {r['period']: dict(r) for r in counts}
    return {'current': values.get('current', {}), 'previous': values.get('previous') if previous_begin else None,
            'daily': [dict(r) for r in daily], 'activity': [dict(r) for r in activity],
            'comparison': bool(previous_begin), 'partial': finish.date() == datetime.now(KST).date(),
            'start_date': start, 'end_date': end, 'generated_at': datetime.now(KST)}
