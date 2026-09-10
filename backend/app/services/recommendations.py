import hashlib
import json
import uuid
from datetime import datetime, timezone
from collections.abc import Sequence
from datetime import date

from app.database import get_pool


_STUDENT_CATEGORY_GROUPS = (
    ("food", ("식품", "간식", "음료", "커피", "라면", "즉석", "냉동", "김치")),
    ("living", ("생활", "세제", "청소", "휴지", "물티슈", "욕실", "위생")),
    ("kitchen", ("주방", "식기", "조리", "보관", "수납")),
    ("appliance", ("가전", "디지털", "전자", "충전", "조명", "선풍기")),
    ("study", ("문구", "도서", "오피스", "책상")),
    ("beauty", ("뷰티", "화장품", "미용", "샴푸", "바디", "치약", "칫솔")),
)
_STUDENT_POSITIVE_KEYWORDS = (
    "간편", "자취", "기숙사", "소형", "미니", "휴대", "일회용", "정리", "세탁",
    "텀블러", "도시락", "수건", "침구", "옷걸이", "이어폰", "키보드", "마우스",
)
_STUDENT_LOW_FIT_CATEGORIES = (
    "가구/홈데코", "반려/애완용품", "유아동", "자동차", "스포츠/레저", "산업용품",
    "교자상/다용도상", "식탁/테이블", "거실테이블", "침대", "매트리스",
    "곤충/생물학", "생물실험세트", "홈세트/식기세트",
)
_STUDENT_EXCLUDED_CATEGORIES = (
    "가구/홈데코", "반려/애완용품", "유아동", "자동차", "산업용품",
    "교자상/다용도상", "식탁/테이블", "거실테이블", "침대", "매트리스",
    "곤충/생물학", "생물실험세트", "홈세트/식기세트",
)


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


async def recent_item_ids(user_id: str | None, hours: int = 24) -> dict[int, object]:
    if not user_id:
        return {}
    try:
        pool = get_pool()
    except RuntimeError:
        return {}
    rows = await pool.fetch(
        """
        SELECT taca_item_id, MAX(created_at) AS last_exposed_at
        FROM user_events
        WHERE user_id = $1
          AND event_name = 'promotion_exposure'
          AND created_at >= NOW() - ($2 * INTERVAL '1 hour')
        GROUP BY taca_item_id
        """,
        user_id,
        hours,
    )
    return {int(row["taca_item_id"]): row["last_exposed_at"] for row in rows}


async def last_exposure_by_product(user_id: str | None, surface: str) -> dict[str, object]:
    """Return the last time each product was shown to a user on one surface."""
    if not user_id:
        return {}
    try:
        pool = get_pool()
    except RuntimeError:
        return {}
    rows = await pool.fetch(
        """
        SELECT product_key, MAX(created_at) AS last_exposed_at
        FROM user_events
        WHERE user_id = $1
          AND surface = $2
          AND event_name = 'promotion_exposure'
          AND product_key IS NOT NULL
        GROUP BY product_key
        """,
        user_id,
        surface,
    )
    return {row["product_key"]: row["last_exposed_at"] for row in rows}


async def latest_item_id(user_id: str | None, surface: str) -> int | None:
    if not user_id:
        return None
    try:
        pool = get_pool()
    except RuntimeError:
        return None
    row = await pool.fetchrow(
        """
        SELECT taca_item_id
        FROM user_events
        WHERE user_id = $1
          AND surface = $2
          AND event_name = 'promotion_exposure'
          AND created_at >= NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        user_id,
        surface,
    )
    return int(row["taca_item_id"]) if row else None


async def record_exposure(
    user_id: str | None,
    surface: str,
    taca_item_id: int,
    category_ids: Sequence[int],
    product_key: str | None = None,
    properties: dict | None = None,
    request_id: str | None = None,
) -> None:
    if not user_id:
        return
    try:
        pool = get_pool()
    except RuntimeError:
        return
    await pool.execute(
        """
        INSERT INTO user_events
            (event_id, user_id, surface, taca_item_id, event_name,
             product_key, request_id, properties)
        VALUES ($1, $2, $3, $4, 'promotion_exposure', $5, $6, $7::jsonb)
        """,
        str(uuid.uuid4()),
        user_id, surface, taca_item_id, product_key, request_id,
        json.dumps({"category_ids": list(category_ids), **(properties or {})}),
    )


async def record_category_click(
    user_id: str | None,
    category_ids: Sequence[int],
    taca_item_id: int | None = None,
    surface: str = "unknown",
    request_id: str | None = None,
) -> None:
    if not user_id:
        return
    try:
        pool = get_pool()
    except RuntimeError:
        return
    async with pool.acquire() as conn:
        if taca_item_id:
            await conn.execute(
                """
                INSERT INTO user_events
                    (event_id, user_id, surface, taca_item_id, event_name, request_id, properties)
                VALUES ($1, $2, $3, $4, 'recommendation_click', $5, $6::jsonb)
                """,
                str(uuid.uuid4()),
                user_id, surface, taca_item_id, request_id,
                json.dumps({"category_ids": list(category_ids)}),
            )
        if not category_ids:
            return
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


def _category_group(item: dict) -> str | None:
    text = " ".join(
        [str(item.get("displayName", ""))]
        + [str(value) for value in item.get("_category_names", [])]
    )
    for group, keywords in _STUDENT_CATEGORY_GROUPS:
        if any(keyword in text for keyword in keywords):
            return group
    return None


def _student_fit_score(item: dict) -> float:
    categories = " ".join(str(value) for value in item.get("_category_names", []))
    text = " ".join(
        [str(item.get("displayName", ""))]
        + [str(value) for value in item.get("_category_names", [])]
    )
    score = 2.0 if _category_group(item) else 0.0
    score += min(
        sum(keyword in text for keyword in _STUDENT_POSITIVE_KEYWORDS) * 0.5,
        2.0,
    )
    score -= min(sum(category in categories for category in _STUDENT_LOW_FIT_CATEGORIES) * 1.5, 4.0)
    score += min(float(item.get("discountRate") or 0), 50.0) / 25.0
    score += min(float(item.get("reviewScore") or 0), 5.0) / 5.0
    return score


def _is_student_excluded(item: dict) -> bool:
    categories = [str(value) for value in item.get("_category_names", [])]
    return any(
        excluded in category
        for category in categories
        for excluded in _STUDENT_EXCLUDED_CATEGORIES
    )


def _candidate_source_score(item: dict) -> float:
    """Give each feed a modest bonus without letting one feed dominate."""
    sources = set(item.get("_candidate_sources") or [])
    score = 0.0
    if "best_selling" in sources:
        score += 0.8
    if "category_best" in sources:
        score += 1.1
    if "today_deals" in sources:
        score += 1.3
        end_at = item.get("_deal_end_at")
        if end_at:
            try:
                remaining_hours = (
                    datetime.fromisoformat(end_at).astimezone(timezone.utc)
                    - datetime.now(timezone.utc)
                ).total_seconds() / 3600
                if 0 < remaining_hours <= 24:
                    score += 0.6
            except (TypeError, ValueError):
                pass
    return score


def rank_candidates(
    items: list[dict],
    affinity: dict[int, float],
    recent_ids: dict[int, object] | set[int] | None = None,
    user_id: str | None = None,
    surface: str = "default",
    selected_groups: set[str] | None = None,
) -> dict | None:
    available = [
        item for item in items
        if not item.get("isSoldOut") and not _is_student_excluded(item)
    ]
    # Prefer a shorter relevant list to filling slots with clearly unsuitable goods.
    if not available:
        available = [item for item in items if not item.get("isSoldOut")]
    if not available:
        return None
    recent_ids = recent_ids or {}
    fresh = [item for item in available if int(item.get("tacaItemId", 0)) not in recent_ids]
    exhausted = not fresh
    if fresh:
        candidates = fresh
    else:
        # Once every candidate was shown, rotate from the least recently shown
        # item instead of falling back to the popularity leader every time.
        candidates = sorted(
            available,
            key=lambda item: recent_ids.get(int(item.get("tacaItemId", 0)))
            if isinstance(recent_ids, dict) else None,
        )

    if exhausted:
        return candidates[0]

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
            + (total - int(item.get("rank") or total)) * 0.1
            + _student_fit_score(item)
            + _candidate_source_score(item)
            - (
                1.5
                if selected_groups
                and _category_group(item) in selected_groups
                else 0.0
            )
        ),
    )


def rank_candidates_ordered(
    items: list[dict],
    affinity: dict[int, float],
    recent_ids: dict[int, object] | set[int] | None = None,
    user_id: str | None = None,
    surface: str = "default",
    limit: int = 5,
) -> list[dict]:
    """Return a ranked list using the same policy as the single-item picker."""
    remaining = list(items)
    ranked: list[dict] = []
    selected_groups: set[str] = set()
    group_counts: dict[str, int] = {}
    while remaining and len(ranked) < limit:
        diverse_remaining = [
            item
            for item in remaining
            if not _category_group(item)
            or group_counts.get(_category_group(item), 0) < 2
        ]
        if diverse_remaining:
            remaining_for_selection = diverse_remaining
        else:
            remaining_for_selection = remaining
        selected = rank_candidates(
            remaining_for_selection,
            affinity,
            recent_ids,
            user_id,
            surface,
            selected_groups,
        )
        if not selected:
            break
        ranked.append(selected)
        group = _category_group(selected)
        if group:
            selected_groups.add(group)
            group_counts[group] = group_counts.get(group, 0) + 1
        selected_id = int(selected.get("tacaItemId", 0))
        remaining = [
            item for item in remaining
            if int(item.get("tacaItemId", 0)) != selected_id
        ]
    return ranked
