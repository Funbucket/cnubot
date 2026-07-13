from dataclasses import dataclass

from app.database import get_pool
from app.utils import common, kakao_json_response


@dataclass
class FavoriteToggleResult:
    place: str
    place_name: str
    added: bool
    remaining_count: int


async def get_favorite_places(user_id: str) -> set[str]:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT place FROM cafeteria_favorites WHERE user_id = $1",
        user_id,
    )
    return {row["place"] for row in rows}


async def set_favorite(user_id: str, place: str, enabled: bool) -> FavoriteToggleResult:
    place_name = common.get_kor_place(place) or place
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if enabled:
                await conn.execute(
                    """
                    INSERT INTO cafeteria_favorites (user_id, place)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id, place) DO NOTHING
                    """,
                    user_id,
                    place,
                )
            else:
                await conn.execute(
                    """
                    DELETE FROM cafeteria_favorites
                    WHERE user_id = $1 AND place = $2
                    """,
                    user_id,
                    place,
                )
            remaining_count = await conn.fetchval(
                "SELECT COUNT(*) FROM cafeteria_favorites WHERE user_id = $1",
                user_id,
            )

    return FavoriteToggleResult(
        place=place,
        place_name=place_name,
        added=enabled,
        remaining_count=remaining_count,
    )


def create_empty_favorites_response():
    kakao_response = kakao_json_response.KakaoJsonResponse()
    card = kakao_response.create_text_card(
        title="즐겨찾기한 식당이 없어요",
        description="자주 보는 식당을 즐겨찾기해두면 여기에서 바로 볼 수 있어요.",
        buttons=[
            {
                "label": "전체 식당 보기",
                "action": "message",
                "messageText": "학식",
            }
        ],
    )
    return kakao_response.add_output_to_response({"textCard": card}).get_response()


async def create_favorites_response(schedule_data: list[dict], favorites: set[str]):
    if not favorites:
        return create_empty_favorites_response()

    favorite_schedules = [
        cafeteria
        for cafeteria in schedule_data
        if cafeteria.get("place") in favorites
    ]
    return _create_favorite_schedule_response(favorite_schedules, favorites)


def create_toggle_response(result: FavoriteToggleResult):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    place_with_object_particle = _with_object_particle(result.place_name)
    if result.added:
        title = f"{place_with_object_particle} 즐겨찾기에 추가했어요"
        buttons = [
            {
                "label": "내 즐겨찾기",
                "action": "message",
                "messageText": "즐겨찾기",
            },
            _create_menu_button(result.place, result.place_name),
        ]
    else:
        title = f"{place_with_object_particle} 즐겨찾기에서 해제했어요"
        description = (
            "이제 즐겨찾기한 식당이 없어요."
            if result.remaining_count == 0
            else "내 즐겨찾기에서 바로 다시 확인할 수 있어요."
        )
        buttons = [
            {
                "label": "전체 식당 보기",
                "action": "message",
                "messageText": "학식",
            }
        ]
        if result.remaining_count > 0:
            buttons.insert(
                0,
                {
                    "label": "내 즐겨찾기",
                    "action": "message",
                    "messageText": "즐겨찾기",
                },
            )
        card = kakao_response.create_text_card(
            title=title,
            description=description,
            buttons=buttons,
        )
        return kakao_response.add_output_to_response({"textCard": card}).get_response()

    card = kakao_response.create_text_card(
        title=title,
        description="자주 보는 식당만 모아서 볼 수 있어요.",
        buttons=buttons,
    )
    return kakao_response.add_output_to_response({"textCard": card}).get_response()


def parse_favorite_place(utterance: str) -> str | None:
    normalized = utterance.replace(" ", "")
    for place, name in common.PLACE_KOREAN.items():
        prefixed_name = f"제{name}" if name[:1].isdigit() else name
        candidates = {
            name.replace(" ", ""),
            prefixed_name.replace(" ", ""),
            name.replace("학생회관", "학").replace(" ", ""),
            place,
        }
        if any(candidate and candidate in normalized for candidate in candidates):
            return place
    return None


def _create_favorite_schedule_response(schedule_data: list[dict], favorites: set[str]):
    from app.services import cafeteria as cafeteria_service

    return cafeteria_service.create_schedule_response(schedule_data, favorites)


def _create_menu_button(place: str, place_name: str) -> dict:
    if place == "hall_1":
        return {
            "action": "webLink",
            "label": "식단 보기",
            "webLinkUrl": f"{common.SERVER_URL}/cafeteria/images/hall_1_menu.png",
        }
    return {
        "action": "message",
        "label": "식단 보기",
        "messageText": f"{common.get_today_in_korean()}{place_name}",
    }


def _with_object_particle(text: str) -> str:
    if not text:
        return text
    last = text[-1]
    if not ("가" <= last <= "힣"):
        return f"{text}을"
    has_final_consonant = (ord(last) - ord("가")) % 28 != 0
    particle = "을" if has_final_consonant else "를"
    return f"{text}{particle}"
