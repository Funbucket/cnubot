import os
from dataclasses import dataclass

import requests
from app.utils import kakao_json_response

KAKAO_LOCAL_CATEGORY_URL = "https://dapi.kakao.com/v2/local/search/category.json"
KAKAO_PLACE_PANEL_URL = "https://place-api.map.kakao.com/places/panel3/{place_id}"
KAKAO_REST_API_KEY = os.getenv("KAKAO_REST_API_KEY")
RESTAURANT_CATEGORY_CODE = "FD6"
KAKAO_PLACE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://place.map.kakao.com",
    "Referer": "https://place.map.kakao.com/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "appVersion": "6.6.0",
    "pf": "PC",
}


@dataclass(frozen=True)
class AreaAnchor:
    label: str
    x: str
    y: str
    radius: int = 1000


AREA_ANCHORS = {
    "dorm": AreaAnchor("기숙사 근처", "127.3442986", "36.3679381"),
    "main": AreaAnchor("충남대 안", "127.3420001", "36.36836824"),
    "front_gate": AreaAnchor("정문 근처", "127.3451925", "36.36221085"),
}


class KakaoLocalConfigError(RuntimeError):
    pass


class KakaoLocalApiError(RuntimeError):
    pass


def search_nearby_restaurants(area: str = "dorm", size: int = 5) -> list[dict]:
    if not KAKAO_REST_API_KEY:
        raise KakaoLocalConfigError("KAKAO_REST_API_KEY is not configured")

    anchor = AREA_ANCHORS.get(area, AREA_ANCHORS["dorm"])
    response = requests.get(
        KAKAO_LOCAL_CATEGORY_URL,
        headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"},
        params={
            "category_group_code": RESTAURANT_CATEGORY_CODE,
            "x": anchor.x,
            "y": anchor.y,
            "radius": anchor.radius,
            "sort": "distance",
            "size": min(max(size, 1), 15),
        },
        timeout=10,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise KakaoLocalApiError("Kakao Local API request failed") from exc
    payload = response.json()
    places = [_normalize_place(place) for place in payload.get("documents", [])]
    return enrich_places_with_menu_prices(places)


def enrich_places_with_menu_prices(places: list[dict]) -> list[dict]:
    enriched_places = []
    for place in places:
        place = {**place}
        try:
            menu_summary = scrape_kakao_place_menu_summary(place["id"])
        except KakaoLocalApiError:
            menu_summary = {}
        enriched_places.append({**place, **menu_summary})
    return enriched_places


def scrape_kakao_place_menu_summary(place_id: str) -> dict:
    if not place_id:
        return {}

    response = requests.get(
        KAKAO_PLACE_PANEL_URL.format(place_id=place_id),
        headers={**KAKAO_PLACE_HEADERS, "Referer": f"https://place.map.kakao.com/{place_id}"},
        timeout=10,
    )
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise KakaoLocalApiError("Kakao place panel request failed") from exc

    payload = response.json()
    menus = _extract_menu_items(payload)
    if not menus:
        return {}

    prices = [menu["price"] for menu in menus if menu.get("price")]
    if not prices:
        return {"menus": menus}

    representative_menus = menus[:3]
    return {
        "menus": menus,
        "min_price": min(prices),
        "representative_menus": representative_menus,
        "menu_updated_at": _extract_menu_updated_at(payload),
    }


def create_nearby_restaurants_response(area: str, places: list[dict]):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    anchor = AREA_ANCHORS.get(area, AREA_ANCHORS["dorm"])

    if not places:
        card = kakao_response.create_text_card(
            title=f"{anchor.label} 음식점을 찾지 못했어요",
            description="잠시 후 다시 조회해 주세요.",
            buttons=[
                {
                    "action": "message",
                    "label": "다시 조회",
                    "messageText": f"{anchor.label} 맛집",
                }
            ],
        )
        return kakao_response.add_output_to_response({"textCard": card}).get_response()

    items = [
        kakao_response.create_text_card(
            title=place["name"],
            description=_create_place_description(place),
            buttons=[
                {
                    "action": "webLink",
                    "label": "지도 보기",
                    "webLinkUrl": place["url"],
                }
            ],
        )
        for place in places
    ]
    kakao_response.add_output_to_response(kakao_response.create_carousel(items))
    kakao_response.add_quick_replies(
        [
            kakao_response.create_quick_reply("7천원 이하", "7천원 이하 맛집"),
            kakao_response.create_quick_reply("1만원 이하", "1만원 이하 맛집"),
            kakao_response.create_quick_reply("1.5만원 이하", "1.5만원 이하 맛집"),
        ]
    )
    return kakao_response.get_response()


def create_kakao_config_required_response():
    kakao_response = kakao_json_response.KakaoJsonResponse()
    card = kakao_response.create_text_card(
        title="카카오 로컬 API 설정이 필요해요",
        description="서버 환경변수 KAKAO_REST_API_KEY를 설정하면 주변 음식점 조회를 사용할 수 있어요.",
        buttons=[],
    )
    return kakao_response.add_output_to_response({"textCard": card}).get_response()


def create_kakao_api_unavailable_response():
    kakao_response = kakao_json_response.KakaoJsonResponse()
    card = kakao_response.create_text_card(
        title="카카오 로컬 API를 사용할 수 없어요",
        description="카카오 개발자 콘솔에서 카카오맵/로컬 서비스가 활성화되어 있는지 확인해 주세요.",
        buttons=[],
    )
    return kakao_response.add_output_to_response({"textCard": card}).get_response()


def get_nearby_restaurants_response(area: str = "dorm"):
    places = search_nearby_restaurants(area=area)
    return create_nearby_restaurants_response(area, places)


def parse_area(utterance: str) -> str:
    normalized = utterance.replace(" ", "")
    if "정문" in normalized:
        return "front_gate"
    if "충남대안" in normalized or "학교안" in normalized or "교내" in normalized:
        return "main"
    return "dorm"


def _normalize_place(place: dict) -> dict:
    return {
        "id": place.get("id", ""),
        "name": place.get("place_name", ""),
        "category": place.get("category_name", ""),
        "address": place.get("road_address_name") or place.get("address_name", ""),
        "phone": place.get("phone", ""),
        "url": place.get("place_url", ""),
        "distance": _parse_int(place.get("distance")),
    }


def _create_place_description(place: dict) -> str:
    lines = []
    category = place.get("category", "").split(">")[-1].strip()
    if category:
        lines.append(category)
    if place.get("min_price"):
        lines.append(f"최저가: {place['min_price']:,}원")
    if place.get("representative_menus"):
        menu_labels = [
            f"{menu['name']} {menu['price']:,}원"
            for menu in place["representative_menus"]
            if menu.get("name") and menu.get("price")
        ]
        if menu_labels:
            lines.append("대표메뉴: " + " / ".join(menu_labels))
    if place.get("distance"):
        lines.append(f"거리: 약 {place['distance']}m")
    if place.get("address"):
        lines.append(place["address"])
    if place.get("phone"):
        lines.append(place["phone"])
    return "\n".join(lines)


def _parse_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _extract_menu_items(payload: dict) -> list[dict]:
    menu = payload.get("menu") or {}
    menus = menu.get("menus") or {}
    return _normalize_menu_items(menus.get("items", []))


def _normalize_menu_items(items: list[dict]) -> list[dict]:
    menus = []
    for item in items:
        name = item.get("name", "").strip()
        price = _parse_int(item.get("price"))
        if not name or price <= 0:
            continue
        menus.append(
            {
                "name": name,
                "price": price,
                "description": item.get("desc", ""),
                "updated_at": item.get("mod_at", ""),
            }
        )
    return menus


def _extract_menu_updated_at(payload: dict) -> str:
    menu = payload.get("menu") or {}
    menus = menu.get("menus") or {}
    return menus.get("items_updated_at", "")
