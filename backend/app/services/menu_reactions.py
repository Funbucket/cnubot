import hashlib
import json
from dataclasses import dataclass

from app.database import get_pool
from app.utils import kakao_json_response

REACTION_LABELS = {
    "positive": "👍 괜찮아요",
    "negative": "👎 아쉬워요",
}


@dataclass
class ReactionResult:
    changed: bool
    positive_count: int
    negative_count: int

    @property
    def total_count(self) -> int:
        return self.positive_count + self.negative_count

    @property
    def positive_percent(self) -> int:
        if not self.total_count:
            return 0
        return round(self.positive_count / self.total_count * 100)

    @property
    def negative_percent(self) -> int:
        if not self.total_count:
            return 0
        return 100 - self.positive_percent


def create_meal_id(
    place_key: str,
    day: str,
    meal_time: str,
    meal_type: str,
    calorie: str,
    menu_items: list[str],
) -> str:
    payload = {
        "place": place_key,
        "day": day,
        "mealTime": meal_time,
        "mealType": meal_type,
        "calorie": calorie or "",
        "menuItems": menu_items,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{place_key}:{day}:{meal_time}:{meal_type}:{digest}"


async def record_reaction(extra: dict, user_id: str) -> ReactionResult:
    reaction = extra.get("reaction")
    if reaction not in REACTION_LABELS:
        raise ValueError("Invalid reaction")

    meal_id = extra.get("mealId")
    if not meal_id:
        raise ValueError("Missing meal id")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO meal_snapshots (
                    meal_id, place, place_name, day, meal_time, meal_type,
                    calorie, menu_items
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                ON CONFLICT (meal_id) DO NOTHING
                """,
                meal_id,
                extra.get("place", ""),
                extra.get("placeName", ""),
                extra.get("day", ""),
                extra.get("mealTime", ""),
                extra.get("mealType", ""),
                extra.get("calorie", ""),
                json.dumps(extra.get("menuItems", []), ensure_ascii=False),
            )
            previous = await conn.fetchval(
                "SELECT reaction FROM meal_reactions WHERE meal_id = $1 AND user_id = $2",
                meal_id,
                user_id,
            )
            await conn.execute(
                """
                INSERT INTO meal_reactions (meal_id, user_id, reaction)
                VALUES ($1, $2, $3)
                ON CONFLICT (meal_id, user_id)
                DO UPDATE SET reaction = EXCLUDED.reaction, updated_at = NOW()
                """,
                meal_id,
                user_id,
                reaction,
            )
            counts = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) FILTER (WHERE reaction = 'positive') AS positive_count,
                    COUNT(*) FILTER (WHERE reaction = 'negative') AS negative_count
                FROM meal_reactions
                WHERE meal_id = $1
                """,
                meal_id,
            )

    return ReactionResult(
        changed=previous is not None and previous != reaction,
        positive_count=counts["positive_count"],
        negative_count=counts["negative_count"],
    )


def create_reaction_response(extra: dict, result: ReactionResult):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    meal_label = "{} {} {}".format(
        extra.get("dayLabel") or extra.get("day", ""),
        extra.get("mealTimeLabel", ""),
        extra.get("mealType", ""),
    ).strip()
    prefix = "투표를 바꿨어요." if result.changed else "투표했어요."

    card = kakao_response.create_text_card(
        title=f"{meal_label} 반응" if meal_label else "식단 반응",
        description=(
            f"{prefix}\n\n"
            f"{REACTION_LABELS['positive']} {result.positive_percent}%\n"
            f"{REACTION_LABELS['negative']} {result.negative_percent}%\n\n"
            f"총 {result.total_count}명 참여"
        ),
        buttons=[{"label": "투표결과 공유하기", "action": "share"}],
    )
    return kakao_response.add_output_to_response({"textCard": card}).get_response()
