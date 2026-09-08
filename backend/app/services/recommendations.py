import hashlib
import json
from collections.abc import Sequence
from datetime import date

from app.database import get_pool


async def category_affinity(user_id: str | None) -> dict[int, float]:
    if not user_id:
        return {}
    try:
        pool = get_pool()
    except RuntimeError:
        return {}
    rows = await pool.fetch(
        """
        SELECT category_id,
               score * POWER(0.5, EXTRACT(EPOCH FROM (NOW() - updated_at)) / 604800.0) AS score
        FROM recommendation_category_affinity
        WHERE user_id = $1
        """,
        user_id,
    )
    return {int(row["category_id"]): float(row["score"]) for row in rows}


async def recent_item_ids(user_id: str | None, hours: int = 24) -> set[int]:
    if not user_id:
        return set()
    try:
        pool = get_pool()
    except RuntimeError:
        return set()
    rows = await pool.fetch(
        """
        SELECT DISTINCT taca_item_id
        FROM recommendation_item_events
        WHERE user_id = $1
          AND event_type = 'exposure'
          AND created_at >= NOW() - ($2 * INTERVAL '1 hour')
        """,
        user_id,
        hours,
    )
    return {int(row["taca_item_id"]) for row in rows}


async def record_exposure(
    user_id: str | None,
    surface: str,
    taca_item_id: int,
    category_ids: Sequence[int],
) -> None:
    if not user_id:
        return
    try:
        pool = get_pool()
    except RuntimeError:
        return
    await pool.execute(
        """
        INSERT INTO recommendation_item_events
            (user_id, surface, taca_item_id, event_type, category_ids)
        VALUES ($1, $2, $3, 'exposure', $4::jsonb)
        """,
        user_id,
        surface,
        taca_item_id,
        json.dumps(list(category_ids)),
    )


async def record_category_click(
    user_id: str | None,
    category_ids: Sequence[int],
    taca_item_id: int | None = None,
    surface: str = "unknown",
) -> None:
    if not user_id or not category_ids:
        return
    try:
        pool = get_pool()
    except RuntimeError:
        return
    async with pool.acquire() as conn:
        if taca_item_id:
            await conn.execute(
                """
                INSERT INTO recommendation_item_events
                    (user_id, surface, taca_item_id, event_type, category_ids)
                VALUES ($1, $2, $3, 'click', $4::jsonb)
                """,
                user_id,
                surface,
                taca_item_id,
                json.dumps(list(category_ids)),
            )
        for category_id in set(int(value) for value in category_ids):
            await conn.execute(
                """
                INSERT INTO recommendation_category_affinity (user_id, category_id, score)
                VALUES ($1, $2, 0.25)
                ON CONFLICT (user_id, category_id)
                DO UPDATE SET
                    score = recommendation_category_affinity.score
                        + CASE WHEN recommendation_category_affinity.click_count = 0 THEN 0.25 ELSE 1 END,
                    click_count = recommendation_category_affinity.click_count + 1,
                    last_clicked_at = NOW(),
                    updated_at = NOW()
                """,
                user_id,
                category_id,
            )


def rank_candidates(
    items: list[dict],
    affinity: dict[int, float],
    recent_ids: set[int] | None = None,
    user_id: str | None = None,
    surface: str = "default",
) -> dict | None:
    available = [item for item in items if not item.get("isSoldOut")]
    if not available:
        return None
    recent_ids = recent_ids or set()
    fresh = [item for item in available if int(item.get("tacaItemId", 0)) not in recent_ids]
    candidates = fresh or available

    if affinity and user_id:
        seed = hashlib.sha256(
            f"{user_id}:{surface}:{date.today().isoformat()}".encode()
        ).digest()[0]
        if seed % 5 == 0:
            unexplored = [
                item for item in candidates[:5]
                if not any(int(category_id) in affinity for category_id in item.get("categoryIds", []))
            ]
            if unexplored:
                return unexplored[0]

    total = max(len(candidates), 1)
    return max(
        candidates,
        key=lambda item: (
            sum(affinity.get(int(category_id), 0) for category_id in item.get("categoryIds", [])) * 10
            + (total - int(item.get("rank", total))) * 0.1
        ),
    )
