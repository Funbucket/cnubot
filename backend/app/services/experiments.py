import hashlib
import json
from typing import Any

from app.database import get_pool


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
        return dict(variant) if variant else None


async def record_event(
    experiment_key: str,
    user_id: str | None,
    event_name: str,
    properties: dict[str, Any] | None = None,
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
                (experiment_id, experiment_key, user_id, variant_key, event_name, properties)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            experiment["id"],
            experiment_key,
            user_id,
            assignment["variant_key"] if assignment else None,
            event_name,
            json.dumps(properties or {}, ensure_ascii=False),
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
        return [dict(row) for row in rows]


async def create_experiment(payload: dict[str, Any], created_by: str) -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            experiment_id = await conn.fetchval(
                """
                INSERT INTO experiments
                    (experiment_key, name, hypothesis, primary_metric,
                     guardrail_metric, allocation, created_by)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                RETURNING id
                """,
                payload["experiment_key"],
                payload["name"],
                payload["hypothesis"],
                payload["primary_metric"],
                payload.get("guardrail_metric"),
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


async def set_experiment_status(experiment_id: int, status: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
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
