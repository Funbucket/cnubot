import hashlib
import json
import re
import secrets
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
            SELECT variant_key FROM experiment_assignments
            WHERE experiment_id = $1 AND user_id = $2
            """,
            experiment["id"],
            user_id,
        )
        await conn.execute(
            """
            INSERT INTO experiment_events
                (experiment_id, experiment_key, user_id, variant_key, event_name,
                 properties, event_id, source)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
            ON CONFLICT DO NOTHING
            """,
            experiment["id"],
            experiment_key,
            user_id,
            assignment["variant_key"] if assignment else None,
            event_name,
            json.dumps(properties or {}, ensure_ascii=False),
            event_id,
            source,
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
            FROM experiment_events
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
            SELECT v.variant_key,
                   COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name = 'promotion_exposure') AS exposed_users,
                   COUNT(DISTINCT e.user_id) FILTER (WHERE e.event_name IN (
                       'promotion_click', 'promotion_button_click',
                       'promotion_quick_reply_click', 'promotion_block_click',
                       'commerce_card_click'
                   )) AS clicked_users
            FROM experiment_variants v
            LEFT JOIN experiment_events e
              ON e.experiment_id = v.experiment_id AND e.variant_key = v.variant_key
            WHERE v.experiment_id = $1
            GROUP BY v.variant_key ORDER BY v.variant_key
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
            "SELECT COUNT(*) FROM experiment_events WHERE experiment_id = $1",
            experiment_id,
        )
        event_breakdown_rows = await conn.fetch(
            """
            SELECT event_name, COUNT(*)::int AS events,
                   COUNT(DISTINCT user_id)::int AS users
            FROM experiment_events
            WHERE experiment_id = $1
            GROUP BY event_name ORDER BY event_name
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
            FROM experiment_events
            WHERE experiment_id = $1
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
