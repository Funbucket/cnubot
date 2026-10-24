"""Restaurant and shuttle aggregates; identifiers never leave the database queries."""
import asyncio
import hashlib

from app.database import get_pool
from app.services.insights_overview import excluded_users


def excluded_hashes():
    return [hashlib.sha256(user.encode()).hexdigest() for user in excluded_users()]


def overview_events(hash_parameter):
    """Normalize the separate restaurant store without double-counting its actions."""
    return f"""WITH events AS (
        SELECT user_id,event_name,properties,created_at FROM user_events
        UNION ALL
        SELECT user_hash,'restaurant_activity',properties,created_at FROM restaurant_events
        WHERE event_name IN ('entry','browse','recommendation')
          AND (user_hash IS NULL OR NOT(user_hash=ANY(${hash_parameter}::text[])))
    ) """


async def summary(service, start=None, end=None):
    if service not in ('restaurants', 'shuttle'):
        raise ValueError('Unknown service')
    if service == 'restaurants':
        source = "SELECT user_hash AS user_key,event_name,properties,created_at FROM restaurant_events"
        excluded = excluded_hashes()
    else:
        source = "SELECT user_id AS user_key,event_name,properties,created_at FROM user_events WHERE event_name='shuttle_view'"
        excluded = excluded_users()
    cte = f"""WITH events AS ({source}), scoped AS (
        SELECT * FROM events WHERE (user_key IS NULL OR NOT(user_key=ANY($3::text[])))
          AND ($1::date IS NULL OR created_at>=($1::date::timestamp AT TIME ZONE 'Asia/Seoul'))
          AND ($2::date IS NULL OR created_at<(($2::date+1)::timestamp AT TIME ZONE 'Asia/Seoul'))
    ) """
    args = (start, end, excluded)
    async with get_pool().acquire() as conn:
        async with conn.transaction(isolation='repeatable_read', readonly=True):
            if service == 'restaurants':
                totals = await conn.fetchrow(cte + """SELECT
                    COUNT(DISTINCT user_key) FILTER(WHERE event_name IN ('entry','browse','recommendation'))::int AS users,
                    COUNT(*) FILTER(WHERE event_name='browse')::int AS views,
                    COUNT(*) FILTER(WHERE event_name='recommendation')::int AS recommendations,
                    COUNT(*) FILTER(WHERE event_name='recommendation' AND properties->>'count'='0')::int AS empty_results,
                    COUNT(*) FILTER(WHERE event_name='recommendation' AND properties->>'refresh'='true')::int AS refreshes,
                    COUNT(DISTINCT user_key) FILTER(WHERE event_name='map_click')::int AS map_users,
                    COUNT(*) FILTER(WHERE event_name='map_click')::int AS map_clicks
                    FROM scoped""", *args)
                daily_fields = """COUNT(DISTINCT user_key) FILTER(WHERE event_name IN ('entry','browse','recommendation'))::int AS users,
                    COUNT(*) FILTER(WHERE event_name='recommendation')::int AS recommendations,
                    COUNT(*) FILTER(WHERE event_name='map_click')::int AS map_clicks"""
                dimensions = [('actions', "properties->>'action'", "event_name='browse'"),
                    ('areas', "properties->>'area'", "event_name='recommendation'"),
                    ('budgets', "properties->>'budget'", "event_name='recommendation'"),
                    ('modes', "COALESCE(properties->>'mode','conditions')", "event_name='recommendation'")]
            else:
                totals = await conn.fetchrow(cte + """SELECT COUNT(DISTINCT user_key)::int AS users,
                    COUNT(*)::int AS views,
                    COUNT(*) FILTER(WHERE properties->>'status'='operating')::int AS operating,
                    COUNT(*) FILTER(WHERE properties->>'status'='before_first')::int AS before_first,
                    COUNT(*) FILTER(WHERE properties->>'status'='ended')::int AS ended,
                    COUNT(*) FILTER(WHERE properties->>'status'='closed')::int AS closed FROM scoped""", *args)
                daily_fields = "COUNT(DISTINCT user_key)::int AS users, COUNT(*)::int AS views"
                dimensions = [('statuses', "properties->>'status'", 'TRUE'),
                              ('reasons', "properties->>'reason'", "properties->>'status'='closed'")]
            daily = await conn.fetch(cte + f"""SELECT (created_at AT TIME ZONE 'Asia/Seoul')::date AS day,
                {daily_fields} FROM scoped GROUP BY 1 ORDER BY 1 DESC LIMIT 30""", *args)
            activity = await conn.fetch(cte + """SELECT
                EXTRACT(ISODOW FROM created_at AT TIME ZONE 'Asia/Seoul')::int AS weekday,
                EXTRACT(HOUR FROM created_at AT TIME ZONE 'Asia/Seoul')::int AS hour, COUNT(*)::int AS events
                FROM scoped WHERE event_name IN ('browse','shuttle_view') GROUP BY 1,2""", *args)
            result = {'totals': dict(totals), 'daily': [dict(r) for r in reversed(daily)],
                      'activity': [dict(r) for r in activity]}
            for key, expression, predicate in dimensions:
                rows = await conn.fetch(cte + f"""SELECT {expression} AS label,
                    COUNT(DISTINCT user_key)::int AS users,COUNT(*)::int AS events
                    FROM scoped WHERE {predicate} AND {expression} IS NOT NULL
                    GROUP BY 1 ORDER BY events DESC,label LIMIT 30""", *args)
                result[key] = [dict(r) for r in rows]
            if service == 'restaurants':
                places = await conn.fetch(cte + """, places AS (
                    SELECT user_key,event_name,p.value AS place_id FROM scoped
                    CROSS JOIN LATERAL jsonb_array_elements_text(
                        CASE WHEN jsonb_typeof(properties->'place_ids')='array'
                             THEN properties->'place_ids' ELSE '[]'::jsonb END) p(value)
                    WHERE event_name='recommendation'
                    UNION ALL
                    SELECT user_key,event_name,properties->>'place_id' FROM scoped WHERE event_name='map_click'
                ) SELECT place_id,
                    COUNT(*) FILTER(WHERE event_name='recommendation')::int AS exposures,
                    COUNT(DISTINCT user_key) FILTER(WHERE event_name='recommendation')::int AS users,
                    COUNT(*) FILTER(WHERE event_name='map_click')::int AS clicks
                    FROM places WHERE place_id IS NOT NULL GROUP BY 1 ORDER BY clicks DESC,exposures DESC,place_id LIMIT 30""", *args)
                result['places'] = [dict(r) for r in places]
    if service == 'restaurants':
        from app.services.restaurant_catalog import safe_catalog
        catalog = await asyncio.to_thread(safe_catalog)
        names = {item.id: item.name for item in catalog.items}
        for place in result['places']:
            place['name'] = names.get(place['place_id'], '현재 목록에 없는 식당')
    return result
