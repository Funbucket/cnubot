import hashlib
import json
import math
import os
import re
import secrets
import uuid
from typing import Any

from app.database import get_pool
from app.services.experiment_stats import minimum_sample_size
from app.services.experiment_stats import compare_proportions


async def get_active_variant(experiment_key: str, user_id: str | None) -> dict[str, Any] | None:
    if not user_id:
        return None

    pool = get_pool()
    async with pool.acquire() as conn:
        experiment = await conn.fetchrow(
            "SELECT id, status FROM experiments WHERE experiment_key = $1",
            experiment_key,
        )
        if not experiment or experiment["status"] != "running":
            return None

        existing = await conn.fetchrow(
            """
            SELECT variant_key FROM experiment_assignments
            WHERE experiment_id = $1 AND user_id = $2
            """,
            experiment["id"],
            user_id,
        )
        if existing:
            variant_key = existing["variant_key"]
        else:
            variants = await conn.fetch(
                """
                SELECT variant_key, label, config, weight
                FROM experiment_variants
                WHERE experiment_id = $1 AND weight > 0
                ORDER BY id
                """,
                experiment["id"],
            )
            if not variants:
                return None
            variant_key = _choose_variant(experiment_key, user_id, variants)
            await conn.execute(
                """
                INSERT INTO experiment_assignments (experiment_id, user_id, variant_key)
                VALUES ($1, $2, $3)
                ON CONFLICT (experiment_id, user_id) DO NOTHING
                """,
                experiment["id"],
                user_id,
                variant_key,
            )

        variant = await conn.fetchrow(
            """
            SELECT variant_key, label, config
            FROM experiment_variants
            WHERE experiment_id = $1 AND variant_key = $2
            """,
            experiment["id"],
            variant_key,
        )
        if not variant:
            return None
        result = dict(variant)
        if isinstance(result.get("config"), str):
            result["config"] = json.loads(result["config"])
        return result


async def record_event(
    experiment_key: str,
    user_id: str | None,
    event_name: str,
    properties: dict[str, Any] | None = None,
    event_id: str | None = None,
    source: str | None = None,
    request_id: str | None = None,
) -> None:
    if not user_id:
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        experiment = await conn.fetchrow(
            "SELECT id FROM experiments WHERE experiment_key = $1",
            experiment_key,
        )

        if not experiment:
            return
        assignment = await conn.fetchrow(
            """
            SELECT a.variant_key, v.config
            FROM experiment_assignments a
            LEFT JOIN experiment_variants v
              ON v.experiment_id = a.experiment_id AND v.variant_key = a.variant_key
            WHERE a.experiment_id = $1 AND a.user_id = $2
            """,
            experiment["id"],
            user_id,
        )
        event_properties = dict(properties or {})
        event_id = event_id or str(uuid.uuid4())
        if "product_key" not in event_properties and assignment and assignment["config"]:
            config = assignment["config"]
            if isinstance(config, str):
                config = json.loads(config)
            if config.get("product_key"):
                event_properties["product_key"] = config["product_key"]
        await conn.execute(
            """
            INSERT INTO user_events
                (experiment_id, experiment_key, user_id, variant_key, event_name,
                properties, event_id, source, request_id)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
            ON CONFLICT DO NOTHING
            """,
            experiment["id"],
            experiment_key,
            user_id,
            assignment["variant_key"] if assignment else None,
            event_name,
            json.dumps(event_properties, ensure_ascii=False),
            event_id,
            source,
            request_id,
        )


async def record_funnel_event(
    user_id: str | None,
    event_name: str,
    source: str | None = None,
    product_key: str | None = None,
    taca_item_id: int | None = None,
    properties: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    """Compatibility wrapper for recording a non-experiment user event."""
    try:
        pool = get_pool()
    except RuntimeError:
        return
    event_id = str(uuid.uuid4())
    event_properties = properties or {}
    await pool.execute(
        """
        INSERT INTO user_events
            (event_id, schema_version, user_id, event_name, source, surface,
             product_key, taca_item_id, request_id, properties)
        VALUES ($1, 1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
        """,
        event_id,
        user_id,
        event_name,
        source,
        event_properties.get("surface"),
        product_key,
        taca_item_id,
        request_id,
        json.dumps(event_properties, ensure_ascii=False),
    )


def _choose_variant(experiment_key: str, user_id: str, variants) -> str:
    total_weight = sum(row["weight"] for row in variants)
    bucket = int(
        hashlib.sha256(f"{experiment_key}:{user_id}".encode()).hexdigest()[:8], 16
    ) % total_weight
    cursor = 0
    for variant in variants:
        cursor += variant["weight"]
        if bucket < cursor:
            return variant["variant_key"]
    return variants[-1]["variant_key"]


async def list_experiments() -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT e.*, COALESCE(json_agg(json_build_object(
                'variant_key', v.variant_key, 'label', v.label, 'config', v.config,
                'weight', v.weight
            ) ORDER BY v.id) FILTER (WHERE v.id IS NOT NULL), '[]') AS variants
            FROM experiments e
            LEFT JOIN experiment_variants v ON v.experiment_id = e.id
            GROUP BY e.id ORDER BY e.created_at DESC
            """
        )
        result = []
        for row in rows:
            item = dict(row)
            if isinstance(item.get("variants"), str):
                item["variants"] = json.loads(item["variants"])
            result.append(item)
        return result


async def create_experiment(payload: dict[str, Any], created_by: str) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            calculated_sample_size = payload.get("min_sample_size")
            if calculated_sample_size is None and payload.get("baseline_rate") and payload.get("mde"):
                calculated_sample_size = minimum_sample_size(
                    payload["baseline_rate"], payload["mde"], payload.get("alpha", 0.05), payload.get("power", 0.8)
                )
            experiment_id = await conn.fetchval(
                """
                INSERT INTO experiments
                    (experiment_key, name, hypothesis, primary_metric,
                     guardrail_metric, unit, alpha, power, baseline_rate, mde,
                     min_sample_size, analysis_plan, allocation, created_by)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13::jsonb, $14)
                RETURNING id
                """,
                payload.get("experiment_key") or generate_experiment_key(payload["name"]),
                payload["name"],
                payload["hypothesis"],
                payload["primary_metric"],
                payload.get("guardrail_metric"),
                payload.get("unit", "user"),
                payload.get("alpha", 0.05),
                payload.get("power", 0.8),
                payload.get("baseline_rate"),
                payload.get("mde"),
                calculated_sample_size,
                json.dumps(payload.get("analysis_plan", {})),
                json.dumps(payload.get("allocation", {})),
                created_by,
            )
            for variant in payload["variants"]:
                await conn.execute(
                    """
                    INSERT INTO experiment_variants
                        (experiment_id, variant_key, label, config, weight)
                    VALUES ($1, $2, $3, $4::jsonb, $5)
                    """,
                    experiment_id,
                    variant["variant_key"],
                    variant["label"],
                    json.dumps(variant.get("config", {}), ensure_ascii=False),
                    variant.get("weight", 50),
                )
            return experiment_id


def generate_experiment_key(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "experiment"
    return f"{slug}-{secrets.token_hex(3)}"


async def set_experiment_status(experiment_id: int, status: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        if status == "running":
            min_sample = await conn.fetchval(
                "SELECT min_sample_size FROM experiments WHERE id = $1",
                experiment_id,
            )
            if not min_sample:
                raise ValueError("실험을 시작하려면 최소 샘플 사이즈를 먼저 설정해야 합니다.")
        await conn.execute(
            """
            UPDATE experiments
            SET status = $2,
                started_at = CASE WHEN $2 = 'running' THEN COALESCE(started_at, NOW()) ELSE started_at END,
                ended_at = CASE WHEN $2 = 'completed' THEN NOW() ELSE ended_at END
            WHERE id = $1
            """,
            experiment_id,
            status,
        )


async def get_results(experiment_id: int) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT variant_key, event_name,
                   COUNT(*)::int AS events,
                   COUNT(DISTINCT user_id)::int AS users
            FROM user_events
            WHERE experiment_id = $1
            GROUP BY variant_key, event_name
            ORDER BY variant_key, event_name
            """,
            experiment_id,
        )
        return [dict(row) for row in rows]


async def get_analysis(experiment_id: int) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        await refresh_rollup(experiment_id, conn)
        experiment = await conn.fetchrow(
            "SELECT * FROM experiments WHERE id = $1", experiment_id
        )
        if not experiment:
            raise ValueError("실험을 찾을 수 없습니다.")
        rows = await conn.fetch(
            """
            SELECT v.variant_key, v.config->>'product_key' AS product_key,
                   COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'promotion_exposure'
                       AND COALESCE(e.properties->>'product_key', v.config->>'product_key') = v.config->>'product_key') AS exposed_users,
                   COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name IN (
                       'promotion_click', 'promotion_button_click',
                       'promotion_quick_reply_click', 'promotion_block_click',
                       'commerce_card_click'
                   ) AND COALESCE(e.properties->>'product_key', v.config->>'product_key') = v.config->>'product_key') AS clicked_users
            FROM experiment_variants v
            LEFT JOIN user_events e
              ON e.experiment_id = v.experiment_id AND e.variant_key = v.variant_key
            WHERE v.experiment_id = $1
            GROUP BY v.variant_key, v.config->>'product_key' ORDER BY v.variant_key
            """,
            experiment_id,
        )
        variants = [dict(row) for row in rows]
        control = next((row for row in variants if row["variant_key"] == "control"), None)
        for row in variants:
            row["conversion_rate"] = (
                row["clicked_users"] / row["exposed_users"]
                if row["exposed_users"]
                else 0
            )
            if control and row["variant_key"] != "control":
                row["comparison"] = compare_proportions(
                    control["clicked_users"], control["exposed_users"],
                    row["clicked_users"], row["exposed_users"],
                )
        total_assigned = await conn.fetchval(
            "SELECT COUNT(*) FROM experiment_assignments WHERE experiment_id = $1",
            experiment_id,
        )
        total_events = await conn.fetchval(
            "SELECT COUNT(*) FROM user_events WHERE experiment_id = $1",
            experiment_id,
        )
        event_breakdown_rows = await conn.fetch(
            """
            SELECT event_name, COALESCE(properties->>'product_key', v.config->>'product_key') AS product_key,
                   COUNT(*)::int AS events,
                   COUNT(DISTINCT e.user_id)::int AS users
            FROM user_events e
            LEFT JOIN experiment_variants v
              ON v.experiment_id = e.experiment_id AND v.variant_key = e.variant_key
            WHERE e.experiment_id = $1
            GROUP BY event_name, COALESCE(properties->>'product_key', v.config->>'product_key')
            ORDER BY event_name, product_key
            """,
            experiment_id,
        )
        assignment_rows = await conn.fetch(
            """
            SELECT a.variant_key, COUNT(*)::int AS users, COALESCE(v.weight, 0) AS weight
            FROM experiment_assignments a
            LEFT JOIN experiment_variants v
              ON v.experiment_id = a.experiment_id AND v.variant_key = a.variant_key
            WHERE a.experiment_id = $1
            GROUP BY a.variant_key, v.weight
            ORDER BY a.variant_key
            """,
            experiment_id,
        )
        srm = _srm_check([dict(row) for row in assignment_rows])
        return {
            "experiment": dict(experiment),
            "variants": variants,
            "assigned_users": total_assigned,
            "events": total_events,
            "event_breakdown": [dict(row) for row in event_breakdown_rows],
            "min_sample_size_per_variant": experiment["min_sample_size"],
            "srm": srm,
            "quality": _quality_summary(experiment, variants, srm),
        }


async def get_promotion_insights(start_date=None, end_date=None) -> dict[str, Any]:
    """Return product and surface aggregates for the promotion dashboard."""
    pool = get_pool()
    click_events = (
        "promotion_click", "promotion_button_click", "promotion_quick_reply_click",
        "promotion_block_click", "commerce_card_click",
    )
    excluded_user_ids = [
        value.strip()
        for value in os.getenv("ANALYTICS_EXCLUDED_USER_IDS", "").split(",")
        if value.strip()
    ]
    async with pool.acquire() as conn:
        product_rows = await conn.fetch(
            """
            WITH normalized AS (
                SELECT COALESCE(e.product_key, e.properties->>'product_key', v.config->>'product_key', 'unknown') AS product_key,
                       e.user_id, e.event_name, e.properties, e.source
                FROM qualified_promotion_events e
                LEFT JOIN experiment_variants v
                  ON v.experiment_id = e.experiment_id AND v.variant_key = e.variant_key
                WHERE ($2::date IS NULL OR e.created_at >= $2::date)
                  AND ($3::date IS NULL OR e.created_at < ($3::date + INTERVAL '1 day'))
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
              AND ($2::date IS NULL OR created_at >= $2::date)
              AND ($3::date IS NULL OR created_at < ($3::date + INTERVAL '1 day'))
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
              AND ($1::date IS NULL OR created_at >= $1::date)
              AND ($2::date IS NULL OR created_at < ($2::date + INTERVAL '1 day'))
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
              AND ($1::date IS NULL OR created_at >= $1::date)
              AND ($2::date IS NULL OR created_at < ($2::date + INTERVAL '1 day'))
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
            WHERE ($2::date IS NULL OR created_at >= $2::date)
              AND ($3::date IS NULL OR created_at < ($3::date + INTERVAL '1 day'))
              AND (user_id IS NULL OR NOT (user_id = ANY($4::text[])))
            GROUP BY day
            ORDER BY day DESC
            LIMIT 30
            """,
            list(click_events), start_date, end_date, excluded_user_ids,
        )
        totals = await conn.fetchrow(
            """
            WITH filtered_events AS (
                SELECT event_name, user_id, created_at
                FROM user_events
                WHERE ($2::date IS NULL OR created_at >= $2::date)
                  AND ($3::date IS NULL OR created_at < ($3::date + INTERVAL '1 day'))
                  AND (user_id IS NULL OR NOT (user_id = ANY($4::text[])))
            ), user_steps AS (
                SELECT user_id,
                       MIN(created_at) FILTER (WHERE event_name = 'promotion_entry_exposure') AS entry_exposure_at,
                       MIN(created_at) FILTER (WHERE event_name = 'promotion_entry_click') AS entry_click_at,
                       MIN(created_at) FILTER (WHERE event_name = 'promotion_exposure') AS product_exposure_at,
                       MIN(created_at) FILTER (WHERE event_name = ANY($1::text[])) AS product_click_at
                FROM filtered_events
                WHERE user_id IS NOT NULL
                GROUP BY user_id
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
        "products": [dict(row) for row in product_rows],
        "surfaces": [dict(row) for row in surface_rows],
        "entry_labels": [dict(row) for row in entry_label_rows],
        "positions": [dict(row) for row in position_rows],
        "daily": [dict(row) for row in daily_rows],
        "totals": dict(totals),
        "start_date": start_date,
        "end_date": end_date,
    }


async def refresh_rollup(experiment_id: int, conn=None) -> None:
    own_connection = conn is None
    pool = get_pool()
    if own_connection:
        conn = await pool.acquire()
    try:
        await conn.execute(
            """
            INSERT INTO experiment_daily_rollups
                (experiment_id, rollup_date, variant_key, event_name, users, events)
            SELECT experiment_id, created_at::date, variant_key, event_name,
                   COUNT(DISTINCT user_id)::int, COUNT(*)::int
            FROM user_events
            WHERE experiment_id = $1 AND variant_key IS NOT NULL
            GROUP BY experiment_id, created_at::date, variant_key, event_name
            ON CONFLICT (experiment_id, rollup_date, variant_key, event_name)
            DO UPDATE SET users = EXCLUDED.users, events = EXCLUDED.events
            """,
            experiment_id,
        )
    finally:
        if own_connection:
            await pool.release(conn)


def _quality_summary(experiment, variants, srm) -> dict[str, Any]:
    min_sample = experiment["min_sample_size"]
    sample_ok = bool(min_sample) and all(
        row["exposed_users"] >= min_sample for row in variants
    )
    comparisons = [row["comparison"] for row in variants if row.get("comparison")]
    significant = bool(comparisons) and all(
        comparison["p_value"] < experiment["alpha"] for comparison in comparisons
    )
    return {
        "sample_size_ok": sample_ok and bool(variants),
        "srm_ok": srm["status"] in {"pass", "insufficient_data"},
        "significant": significant,
        "decision_ready": sample_ok and srm["status"] == "pass" and significant,
        "alpha": experiment["alpha"],
        "power": experiment["power"],
    }


def _srm_check(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = sum(row["users"] for row in rows)
    weight_total = sum(row["weight"] for row in rows)
    if not total or not weight_total or len(rows) < 2:
        return {"p_value": None, "status": "insufficient_data"}
    chi_square = sum(
        ((row["users"] - total * row["weight"] / weight_total) ** 2)
        / (total * row["weight"] / weight_total)
        for row in rows
        if row["weight"] > 0
    )
    # Two-arm SRM uses a one-degree-of-freedom chi-square approximation.
    p_value = math.erfc(math.sqrt(chi_square / 2))
    return {
        "p_value": p_value,
        "status": "pass" if p_value >= 0.001 else "fail",
        "observed": {row["variant_key"]: row["users"] for row in rows},
    }
