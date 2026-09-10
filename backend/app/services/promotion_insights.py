"""Promotion dashboard queries and aggregation, independent of experiment assignment."""
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

_PATH_EVENTS_CTE = """
                SELECT user_id, event_name, created_at,
                       CASE WHEN surface = 'menu_inline_card' THEN 'inline' ELSE 'entry' END AS path
                FROM qualified_promotion_events
                WHERE ($2::date IS NULL OR created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                  AND ($3::date IS NULL OR created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                  AND (user_id IS NULL OR NOT (user_id = ANY($4::text[])))
                  -- Keep each funnel step inside the selected period. The
                  -- qualification view intentionally looks at historical
                  -- events, but a dashboard period must not inherit a
                  -- button click from an exposure before that period.
                  AND (
                    event_name <> 'promotion_entry_click'
                    OR EXISTS (
                      SELECT 1 FROM qualified_promotion_events p
                      WHERE p.user_id = qualified_promotion_events.user_id
                        AND p.event_name = 'promotion_entry_exposure'
                        AND p.created_at <= qualified_promotion_events.created_at
                        AND ($2::date IS NULL OR p.created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                        AND ($3::date IS NULL OR p.created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                    )
                  )
                  AND (
                    event_name <> 'promotion_exposure'
                    OR EXISTS (
                      SELECT 1 FROM qualified_promotion_events c
                      JOIN qualified_promotion_events p
                        ON p.user_id = c.user_id
                       AND p.event_name = 'promotion_entry_exposure'
                       AND p.created_at <= c.created_at
                      WHERE c.user_id = qualified_promotion_events.user_id
                        AND c.event_name = 'promotion_entry_click'
                        AND c.created_at <= qualified_promotion_events.created_at
                        AND ($2::date IS NULL OR c.created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                        AND ($3::date IS NULL OR c.created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                        AND ($2::date IS NULL OR p.created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                        AND ($3::date IS NULL OR p.created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                    )
                  )
                  AND (
                    event_name NOT IN ('promotion_click', 'promotion_button_click', 'promotion_quick_reply_click', 'promotion_block_click', 'commerce_card_click')
                    OR EXISTS (
                      SELECT 1 FROM qualified_promotion_events x
                      JOIN qualified_promotion_events c
                        ON c.user_id = x.user_id
                       AND c.event_name = 'promotion_entry_click'
                       AND c.created_at <= x.created_at
                      JOIN qualified_promotion_events p
                        ON p.user_id = c.user_id
                       AND p.event_name = 'promotion_entry_exposure'
                       AND p.created_at <= c.created_at
                      WHERE x.user_id = qualified_promotion_events.user_id
                        AND x.event_name = 'promotion_exposure'
                        AND x.created_at <= qualified_promotion_events.created_at
                        AND ($2::date IS NULL OR x.created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                        AND ($3::date IS NULL OR x.created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                        AND ($2::date IS NULL OR c.created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                        AND ($3::date IS NULL OR c.created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                        AND ($2::date IS NULL OR p.created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                        AND ($3::date IS NULL OR p.created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                    )
                  )
"""


async def get_promotion_insights(pool, start_date=None, end_date=None) -> dict[str, Any]:
    """Return product and surface aggregates for the promotion dashboard."""
    click_events = (
        "promotion_click", "promotion_button_click", "promotion_quick_reply_click",
        "promotion_block_click", "commerce_card_click",
    )
    developer_id = os.getenv("DEVELOPER_ID", "").strip()
    excluded_user_ids = [developer_id] if developer_id else []
    async with pool.acquire() as conn:
        product_rows = await conn.fetch(
            """
            WITH normalized AS (
                SELECT COALESCE(e.product_key, e.properties->>'product_key', v.config->>'product_key', 'unknown') AS product_key,
                       e.user_id, e.event_name, e.properties, e.source
                FROM qualified_promotion_events e
                LEFT JOIN experiment_variants v
                  ON v.experiment_id = e.experiment_id AND v.variant_key = e.variant_key
                WHERE ($2::date IS NULL OR e.created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                  AND ($3::date IS NULL OR e.created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                  AND (e.user_id IS NULL OR NOT (e.user_id = ANY($4::text[])))
            )
            SELECT product_key,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure')::int AS exposed_users,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = ANY($1::text[]))::int AS clicked_users,
                   COUNT(*) FILTER (WHERE event_name = ANY($1::text[]))::int AS click_events,
                   COALESCE(MAX(properties->>'product_name') FILTER (WHERE properties->>'product_name' IS NOT NULL), '') AS product_name,
                   COALESCE(MAX(properties->>'category_name') FILTER (WHERE properties->>'category_name' IS NOT NULL), '') AS category_name,
                   COALESCE(MAX(properties->>'entry_button_id') FILTER (WHERE properties->>'entry_button_id' IS NOT NULL), '') AS entry_button_id,
                   COALESCE(MAX(properties->>'entry_button_label') FILTER (WHERE properties->>'entry_button_label' IS NOT NULL), '') AS entry_button_label,
                   COALESCE(string_agg(DISTINCT NULLIF(source, ''), ', ') FILTER (WHERE event_name = 'promotion_exposure'), '') AS entry_sources,
                   COALESCE(string_agg(DISTINCT CASE WHEN event_name = 'commerce_card_click' THEN 'commerce_card' ELSE NULLIF(properties->>'surface', '') END, ', ') FILTER (WHERE event_name = ANY($1::text[])), '') AS click_surfaces
            FROM normalized
            GROUP BY product_key
            ORDER BY clicked_users DESC, exposed_users DESC, product_key
            """,
            list(click_events), start_date, end_date, excluded_user_ids,
        )
        surface_rows = await conn.fetch(
            """
            WITH all_events AS (
                SELECT event_name, user_id, properties, source, created_at
                FROM qualified_promotion_events
            )
            SELECT CASE
                       WHEN event_name = 'promotion_entry_click' THEN COALESCE(properties->>'entry_source', source, 'unknown')
                       WHEN event_name = 'promotion_quick_reply_click' THEN 'quick_reply'
                       WHEN event_name = 'commerce_card_click' THEN 'commerce_card'
                       WHEN event_name = 'promotion_button_click' THEN 'menu_button'
                       WHEN event_name IN ('promotion_click', 'promotion_block_click') THEN 'promotion_block'
                       ELSE COALESCE(properties->>'surface', source, 'unknown')
                   END AS surface,
                   COUNT(DISTINCT user_id)::int AS users,
                   COUNT(*)::int AS events
            FROM all_events
            WHERE event_name = ANY($1::text[])
              AND event_name IN ('promotion_entry_click', 'promotion_button_click', 'promotion_quick_reply_click', 'commerce_card_click')
              AND ($2::date IS NULL OR created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
              AND ($3::date IS NULL OR created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
              AND (user_id IS NULL OR NOT (user_id = ANY($4::text[])))
            GROUP BY 1
            ORDER BY users DESC, surface
            """,
            list(click_events), start_date, end_date, excluded_user_ids,
        )
        entry_label_rows = await conn.fetch(
            """
            WITH all_events AS (
                SELECT event_name, user_id, properties, source, created_at
                FROM qualified_promotion_events
            )
            SELECT COALESCE(properties->>'button_label', properties->>'entry_button_label', '') AS label,
                   COALESCE(properties->>'entry_source', source, 'unknown') AS source,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_entry_exposure')::int AS exposed_users,
                   COUNT(*) FILTER (WHERE event_name = 'promotion_entry_exposure')::int AS exposure_events,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_entry_click')::int AS entry_users,
                   COUNT(*) FILTER (WHERE event_name = 'promotion_entry_click')::int AS entry_events,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'commerce_card_click')::int AS card_clicked_users,
                   COUNT(*) FILTER (WHERE event_name = 'commerce_card_click')::int AS card_click_events
            FROM all_events
            WHERE event_name IN ('promotion_entry_exposure', 'promotion_entry_click', 'commerce_card_click')
              AND NULLIF(COALESCE(properties->>'button_label', properties->>'entry_button_label', ''), '') IS NOT NULL
              AND ($1::date IS NULL OR created_at >= ($1::date::timestamp AT TIME ZONE 'Asia/Seoul'))
              AND ($2::date IS NULL OR created_at < (($2::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
              AND (user_id IS NULL OR NOT (user_id = ANY($3::text[])))
            GROUP BY 1, 2
            ORDER BY exposed_users DESC, exposure_events DESC, label
            """,
            start_date, end_date, excluded_user_ids,
        )
        position_rows = await conn.fetch(
            """
            WITH all_events AS (
                SELECT event_name, user_id, properties, created_at
                FROM qualified_promotion_events
            )
            SELECT (properties->>'position')::int AS position,
                   MAX((properties->>'row')::int)::int AS row,
                   MAX((properties->>'column')::int)::int AS column,
                   COUNT(*) FILTER (WHERE event_name = 'promotion_exposure')::int AS exposed_events,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure')::int AS exposed_users,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'commerce_card_click')::int AS clicked_users,
                   COUNT(*) FILTER (WHERE event_name = 'commerce_card_click')::int AS click_events
            FROM all_events
            WHERE event_name IN ('promotion_exposure', 'commerce_card_click')
              AND (properties->>'position') ~ '^[0-9]+$'
              AND ($1::date IS NULL OR created_at >= ($1::date::timestamp AT TIME ZONE 'Asia/Seoul'))
              AND ($2::date IS NULL OR created_at < (($2::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
              AND (user_id IS NULL OR NOT (user_id = ANY($3::text[])))
            GROUP BY 1
            ORDER BY position
            """,
            start_date, end_date, excluded_user_ids,
        )
        daily_rows = await conn.fetch(
            """
            WITH all_events AS (
                SELECT event_name, user_id, created_at
                FROM qualified_promotion_events
            )
            SELECT (created_at AT TIME ZONE 'Asia/Seoul')::date AS day,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure')::int AS exposed_users,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = ANY($1::text[]))::int AS clicked_users,
                   COUNT(*) FILTER (WHERE event_name = ANY($1::text[]))::int AS click_events
            FROM all_events
            WHERE ($2::date IS NULL OR created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
              AND ($3::date IS NULL OR created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
              AND (user_id IS NULL OR NOT (user_id = ANY($4::text[])))
            GROUP BY day
            ORDER BY day DESC
            LIMIT 30
            """,
            list(click_events), start_date, end_date, excluded_user_ids,
        )
        # 인라인 카드에는 진입 클릭 단계가 없어 경로별로 따로 집계해야 한다.
        path_rows = await conn.fetch(
            f"""
            WITH events AS ({_PATH_EVENTS_CTE})
            SELECT path,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_entry_exposure')::int AS entry_exposed_users,
                   COUNT(*) FILTER (WHERE event_name = 'promotion_entry_exposure')::int AS entry_exposure_events,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_entry_click')::int AS entry_users,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure')::int AS exposed_users,
                   COUNT(*) FILTER (WHERE event_name = 'promotion_exposure')::int AS exposure_events,
                   COUNT(DISTINCT user_id) FILTER (WHERE event_name = ANY($1::text[]))::int AS clicked_users,
                   COUNT(*) FILTER (WHERE event_name = ANY($1::text[]))::int AS click_events
            FROM events
            GROUP BY path
            """,
            list(click_events), start_date, end_date, excluded_user_ids,
        )
        # 같은 접점을 반복해서 본 사용자의 반응률이 떨어지는지 본다.
        fatigue_rows = await conn.fetch(
            f"""
            WITH events AS ({_PATH_EVENTS_CTE}), impressions AS (
                SELECT user_id, path, created_at,
                       ROW_NUMBER() OVER (PARTITION BY user_id, path ORDER BY created_at) AS nth,
                       LEAD(created_at) OVER (PARTITION BY user_id, path ORDER BY created_at) AS next_at
                FROM events
                WHERE (path = 'entry' AND event_name = 'promotion_entry_exposure')
                   OR (path = 'inline' AND event_name = 'promotion_exposure')
            ), actions AS (
                SELECT user_id, path, created_at
                FROM events
                WHERE (path = 'entry' AND event_name = 'promotion_entry_click')
                   OR (path = 'inline' AND event_name = ANY($1::text[]))
            )
            SELECT i.path, LEAST(i.nth, 6)::int AS nth,
                   COUNT(*)::int AS impressions,
                   COUNT(*) FILTER (WHERE EXISTS (
                       SELECT 1 FROM actions a
                       WHERE a.user_id = i.user_id AND a.path = i.path
                         AND a.created_at >= i.created_at
                         AND (i.next_at IS NULL OR a.created_at < i.next_at)
                   ))::int AS actions
            FROM impressions i
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            list(click_events), start_date, end_date, excluded_user_ids,
        )
        # 가드레일: 광고를 본 응답만이 아니라 학식 사용 전체를 기준으로 본다.
        guardrail_rows = await conn.fetch(
            """
            WITH visit_events AS (
                SELECT user_id, event_name,
                       (created_at AT TIME ZONE 'Asia/Seoul')::date AS day
                FROM user_events
                WHERE user_id IS NOT NULL
                  AND event_name IN ('menu_view', 'promotion_entry_exposure', 'promotion_exposure')
                  AND ($1::date IS NULL OR created_at >= ($1::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                  AND ($2::date IS NULL OR created_at < (($2::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                  AND NOT (user_id = ANY($3::text[]))
            ), visits AS (
                SELECT DISTINCT user_id, day FROM visit_events
            ), menu_views AS (
                SELECT day, user_id, COUNT(*)::int AS views
                FROM visit_events WHERE event_name = 'menu_view'
                GROUP BY day, user_id
            )
            SELECT v.day,
                   COUNT(DISTINCT v.user_id)::int AS active_users,
                   COUNT(DISTINCT v.user_id) FILTER (WHERE EXISTS (
                       SELECT 1 FROM visits n
                       WHERE n.user_id = v.user_id AND n.day = v.day + 1
                   ))::int AS returned_users,
                   COALESCE(SUM(m.views), 0)::int AS menu_views,
                   COUNT(DISTINCT m.user_id)::int AS menu_view_users
            FROM visits v
            LEFT JOIN menu_views m ON m.user_id = v.user_id AND m.day = v.day
            GROUP BY v.day
            ORDER BY v.day DESC
            LIMIT 14
            """,
            start_date, end_date, excluded_user_ids,
        )
        totals = await conn.fetchrow(
            """
            WITH filtered_events AS (
                SELECT event_name, user_id, created_at
                FROM user_events
                WHERE ($2::date IS NULL OR created_at >= ($2::date::timestamp AT TIME ZONE 'Asia/Seoul'))
                  AND ($3::date IS NULL OR created_at < (($3::date + INTERVAL '1 day') AT TIME ZONE 'Asia/Seoul'))
                  AND (user_id IS NULL OR NOT (user_id = ANY($4::text[])))
            ), entry_exposures AS (
                SELECT user_id,
                       MIN(created_at) AS entry_exposure_at
                FROM filtered_events
                WHERE user_id IS NOT NULL AND event_name = 'promotion_entry_exposure'
                GROUP BY user_id
            ), entry_clicks AS (
                SELECT x.*, (SELECT MIN(e.created_at) FROM filtered_events e
                    WHERE e.user_id = x.user_id AND e.event_name = 'promotion_entry_click'
                      AND e.created_at >= x.entry_exposure_at) AS entry_click_at
                FROM entry_exposures x
            ), product_exposures AS (
                SELECT x.*, (SELECT MIN(e.created_at) FROM filtered_events e
                    WHERE e.user_id = x.user_id AND e.event_name = 'promotion_exposure'
                      AND e.created_at >= x.entry_click_at) AS product_exposure_at
                FROM entry_clicks x
            ), user_steps AS (
                SELECT x.*, (SELECT MIN(e.created_at) FROM filtered_events e
                    WHERE e.user_id = x.user_id AND e.event_name = ANY($1::text[])
                      AND e.created_at >= x.product_exposure_at) AS product_click_at
                FROM product_exposures x
            )
            SELECT COUNT(*) FILTER (WHERE entry_exposure_at IS NOT NULL)::int AS entry_exposed_users,
                   COUNT(*) FILTER (WHERE entry_exposure_at IS NOT NULL
                                         AND entry_click_at >= entry_exposure_at)::int AS entry_users,
                   COUNT(*) FILTER (WHERE entry_exposure_at IS NOT NULL
                                         AND entry_click_at IS NOT NULL
                                         AND product_exposure_at >= entry_click_at)::int AS exposed_users,
                   COUNT(*) FILTER (WHERE entry_exposure_at IS NOT NULL
                                         AND entry_click_at IS NOT NULL
                                         AND product_exposure_at IS NOT NULL
                                         AND product_click_at >= product_exposure_at)::int AS clicked_users,
                   (SELECT COUNT(*) FROM filtered_events WHERE event_name = 'promotion_entry_exposure')::int AS entry_exposure_events,
                   (SELECT COUNT(*) FROM filtered_events WHERE event_name = 'promotion_entry_click')::int AS entry_events,
                   (SELECT COUNT(*) FROM filtered_events WHERE event_name = 'promotion_exposure')::int AS exposure_events,
                   (SELECT COUNT(*) FROM filtered_events WHERE event_name = ANY($1::text[]))::int AS click_events,
                   (SELECT COUNT(*) FROM filtered_events)::int AS events
            FROM user_steps
            """,
            list(click_events), start_date, end_date, excluded_user_ids,
        )
    return {
        "paths": _summarize_paths(path_rows),
        "guardrails": _summarize_guardrails(guardrail_rows),
        "fatigue": [dict(row) for row in fatigue_rows],
        "products": [dict(row) for row in product_rows],
        "surfaces": [dict(row) for row in surface_rows],
        "entry_labels": [dict(row) for row in entry_label_rows],
        "positions": [dict(row) for row in position_rows],
        "daily": [dict(row) for row in daily_rows],
        "totals": dict(totals),
        "start_date": start_date,
        "end_date": end_date,
    }


def _summarize_paths(rows) -> list[dict[str, Any]]:
    """Describe each path with the same reach → 반응 → 클릭 shape.

    진입형은 버튼을 본 사람이 접점 노출이고, 인라인형은 상품 카드 자체가 접점이다.
    """
    summaries = []
    for row in rows:
        item = dict(row)
        if item["path"] == "inline":
            item["reach_users"] = item["exposed_users"]
            item["reach_events"] = item["exposure_events"]
            item["action_users"] = item["clicked_users"]
            item["steps"] = 2
        else:
            item["reach_users"] = item["entry_exposed_users"]
            item["reach_events"] = item["entry_exposure_events"]
            item["action_users"] = item["entry_users"]
            item["steps"] = 4
        item["action_rate"] = _rate(item["action_users"], item["reach_users"])
        item["click_rate"] = _rate(item["clicked_users"], item["reach_users"])
        item["impression_click_rate"] = _rate(item["click_events"], item["reach_events"])
        item["impressions_per_user"] = (
            item["reach_events"] / item["reach_users"] if item["reach_users"] else 0
        )
        summaries.append(item)
    return sorted(summaries, key=lambda item: item["reach_users"], reverse=True)


def _summarize_guardrails(rows, today=None) -> list[dict[str, Any]]:
    """Daily retention and re-query volume.

    다음 날이 아직 진행 중이면 재방문율이 낮게 나오므로 확정값으로 쓰지 않는다.
    다음 날 활동이 통째로 비어 있으면 0%가 아니라 측정 불가로 다뤄야 한다.
    수집이 멈춘 날이나 오늘을 이탈로 읽으면 가드레일이 거짓 경보를 낸다.
    """
    summaries = []
    today = today or datetime.now(ZoneInfo("Asia/Seoul")).date()
    active_days = {row["day"] for row in rows if row["active_users"]}
    for row in rows:
        item = dict(row)
        next_day = item["day"] + timedelta(days=1)
        item["return_rate"] = _rate(item["returned_users"], item["active_users"])
        item["views_per_user"] = (
            item["menu_views"] / item["menu_view_users"] if item["menu_view_users"] else 0
        )
        item["return_rate_pending"] = next_day >= today
        item["return_rate_measurable"] = (
            next_day in active_days and next_day < today
        )
        summaries.append(item)
    return summaries


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator * 100 if denominator else 0.0
