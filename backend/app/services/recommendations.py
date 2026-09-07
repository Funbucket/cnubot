from collections.abc import Sequence

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
        SELECT category_id, score
        FROM recommendation_category_affinity
        WHERE user_id = $1
        """,
        user_id,
    )
    return {int(row["category_id"]): float(row["score"]) for row in rows}


async def record_category_click(user_id: str | None, category_ids: Sequence[int]) -> None:
    if not user_id or not category_ids:
        return
    try:
        pool = get_pool()
    except RuntimeError:
        return
    async with pool.acquire() as conn:
        for category_id in set(int(value) for value in category_ids):
            await conn.execute(
                """
                INSERT INTO recommendation_category_affinity (user_id, category_id, score)
                VALUES ($1, $2, 1)
                ON CONFLICT (user_id, category_id)
                DO UPDATE SET score = recommendation_category_affinity.score + 1,
                              updated_at = NOW()
                """,
                user_id,
                category_id,
            )


def rank_candidates(items: list[dict], affinity: dict[int, float]) -> dict | None:
    available = [item for item in items if not item.get("isSoldOut")]
    if not available:
        return None
    if not affinity:
        return available[0]

    total = max(len(available), 1)
    return max(
        available,
        key=lambda item: (
            sum(affinity.get(int(category_id), 0) for category_id in item.get("categoryIds", [])) * 10
            + (total - int(item.get("rank", total))) * 0.01
        ),
    )
