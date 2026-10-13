"""Discover with Kakao Local, read only public menu and aggregate rating fields.

The public page adapter is deliberately separate from the documented Local API.
It does not authenticate, solve challenges, retain reviews, or persist raw pages.
"""
import fcntl
import json
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

from app.schemas.restaurants import Catalog, Meal, Rating, Restaurant
from app.services import restaurant_catalog as store
from app.utils.json_files import write_json_atomic

AREAS = ("궁동", "어은동", "죽동")
PUBLIC_PANEL = "https://place.map.kakao.com/places/panel3/{place_id}"
COLLECT_INTERVAL = timedelta(hours=6)
REQUEST_DELAY = 0.5
SIDE = re.compile(r"음료|콜라|사이다|주스|쥬스|맥주|소주|막걸리|와인|하이볼|위스키|칵테일|커피|아메리카노|라떼|에이드|티라미수|디저트|추가|토핑|사리|공기밥|볶음공기|셀프|치즈만|어린이|아동|유아|초등|[0-9]+\s*[~～-]\s*[0-9]+\s*세")
WEIGHT = re.compile(r"[0-9]+\s*(?:g|그램|kg)|시가|변동|최소|이상|부터|(?:[2-9]|[1-9][0-9]+)\s*인|대\s*\)|중\s*\)|소\s*\)", re.I)
MEAL_WORDS = re.compile(r"정식|백반|덮밥|비빔밥|국밥|볶음밥|오므라이스|카레|돈까스|돈가스|치킨까스|생선까스|파스타|스파게티|리조또|라멘|라면|우동|소바|메밀|냉면|칼국수|쌀국수|잔치국수|비빔국수|짜장|자장|짬뽕|마라탕|찌개|해장국|설렁탕|곰탕|순대국|추어탕|삼계탕|갈비탕|육개장|뚝배기|김밥|도시락|초밥|스시|함박|스테이크|햄버거|버거|샌드위치|피자|포케|쌀면|팟타이|수제비|쫄면|샐러드|한상|불고기|제육|두루치기|닭갈비|오마카세|코스|런치|디너")


def status_path() -> Path:
    return store.catalog_path().with_name("restaurants_collection.json")


def read_status() -> dict:
    try:
        value = json.loads(status_path().read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def save_status(value):
    path = status_path()
    write_json_atomic(value, path.parent, path.name)


def _get_json(session, url, **kwargs):
    response = session.get(url, timeout=(3, 8), **kwargs)
    # Stop on access controls; no alternate identity, proxy, challenge or login.
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("Unexpected public response")
    return data


def discover(session, area, key, pages=2):
    places = []
    for page in range(1, pages + 1):
        data = _get_json(session, "https://dapi.kakao.com/v2/local/search/keyword.json",
            headers={"Authorization": "KakaoAK " + key},
            params={"query": f"대전 {area} 음식점", "category_group_code": "FD6", "size": 15, "page": page})
        if not isinstance(data.get("documents"), list) or not isinstance(data.get("meta"), dict):
            raise ValueError("Unexpected Local search response")
        for place in data["documents"]:
            if (isinstance(place, dict) and re.fullmatch(r"[0-9]+", str(place.get("id", "")))
                    and f"대전 유성구 {area} " in str(place.get("address_name", ""))):
                places.append(place)
        if data["meta"].get("is_end"):
            break
        time.sleep(REQUEST_DELAY)
    return list({place["id"]: place for place in places}.values())


def _updated_on(value):
    try:
        parsed = datetime.fromisoformat(str(value)).date()
        return parsed if parsed <= store.today_kst() else None
    except ValueError:
        return None


def parse_public_place(place: dict, area: str, payload: dict, now: datetime) -> Restaurant | None:
    """Whitelist only explicit prices, meal names and aggregate scores."""
    summary = payload.get("summary")
    menu = payload.get("menu")
    if not isinstance(summary, dict) or not isinstance(menu, dict) or not isinstance(menu.get("menus"), dict):
        raise ValueError("Public place structure changed")
    if str(summary.get("confirm_id")) != str(place["id"]):
        raise ValueError("Place identity mismatch")
    if summary.get("status") != "Y":
        return None
    address = summary.get("address") or {}
    if not isinstance(address, dict) or not str(address.get("jibun", "")).startswith(area + " "):
        raise ValueError("Place district mismatch")
    category = summary.get("category") or {}
    if not isinstance(category, dict) or category.get("name1") != "음식점":
        return None
    cuisine = str(category.get("name2") or category.get("name") or "음식점")[:10]
    menus = menu["menus"]
    if not isinstance(menus.get("items", []), list):
        raise ValueError("Menu structure changed")
    place_url = "https://place.map.kakao.com/" + str(place["id"])
    meals = []
    for row in menus.get("items", []):
        if not isinstance(row, dict):
            continue
        name, price = row.get("name"), row.get("price")
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 35:
            continue
        # Variable prices, shared portions, minimum orders and weight units are
        # not exact one-person meal costs. Missing details are never inferred.
        details = name + " " + str(row.get("desc") or "")
        if SIDE.search(details) or WEIGHT.search(details):
            continue
        if type(price) is not int or not 3000 <= price <= 1000000:
            continue
        if not MEAL_WORDS.search(name) and not (category.get("name") == "피자" and price >= 10000):
            continue
        meals.append(Meal(name=name.strip(), total_price=price, diners=1,
            source=place_url, checked_on=now.date(),
            source_updated_on=_updated_on(row.get("mod_at") or menus.get("items_updated_at"))))
    meals = list({(meal.name, meal.total_price): meal for meal in meals}.values())
    if not meals:
        return None
    # Ensure more expensive bands are not lost when a restaurant has >10 menus.
    by_price = sorted(meals, key=lambda meal: meal.total_price)
    selected = []
    for low, high in [(0, 10000), (10000, 20000), (20000, None)]:
        band = [meal for meal in by_price if meal.total_price >= low and (high is None or meal.total_price < high)]
        selected.extend(band[:3])
    for meal in by_price:
        if len(selected) == 10:
            break
        if meal not in selected:
            selected.append(meal)
    rating = None
    reviews = payload.get("kakaomap_review") or {}
    score_set = reviews.get("score_set") if isinstance(reviews, dict) else None
    if isinstance(score_set, dict):
        score, count = score_set.get("average_score"), score_set.get("review_count")
        if type(score) in (int, float) and type(count) is int and count > 0:
            try:
                rating = Rating(score=score, count=count, checked_at=now)
            except ValueError:
                pass
    return Restaurant(id="kakao_" + str(place["id"]), name=str(summary.get("name") or place["place_name"])[:35],
        area=area, cuisine=cuisine, place_url=place_url, enabled=True,
        reason="카카오맵 등록 메뉴", evidence="카카오 Local 주소와 공개 장소 메뉴 확인",
        meals=selected, rating=rating, origin="kakao_public")


def merge_results(current: Catalog, outcomes: dict[str, Restaurant | None], now: datetime) -> Catalog:
    items = []
    handled = set()
    for item in current.items:
        place_id = item.place_url.rsplit("/", 1)[-1]
        handled.add(place_id)
        if item.origin != "kakao_public" or place_id not in outcomes:
            items.append(item)
        elif outcomes[place_id] is not None:
            updated = outcomes[place_id].model_copy(update={"enabled": item.enabled})
            items.append(updated)
        # A successfully read inactive/menu-less page removes only auto entries.
        # Failed page requests are absent from outcomes and preserve old entries.
    items.extend(item for place_id, item in outcomes.items() if item is not None and place_id not in handled)
    if len(items) > 200:
        items = items[:200]
    enable = current.ratings_enabled
    basis = current.rating_usage_basis
    if not basis and any(item.rating for item in items):
        enable = True
        basis = "사용자 요청에 따른 카카오맵 공개 장소 페이지 집계 평점 수집"
    return current.model_copy(update={"items": items, "ratings_enabled": enable, "rating_usage_basis": basis})


def collect(pages=2):
    key = os.getenv("KAKAO_REST_API_KEY", "")
    if not key:
        raise RuntimeError("Kakao Local key is missing")
    path = store.catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name("restaurants_collection.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return read_status()
        now = store.now_kst()
        previous = read_status()
        status = {"status": "running", "started_at": now.isoformat(),
                  "last_success_at": previous.get("last_success_at"), "areas": {}, "page_failures": 0}
        save_status(status)
        outcomes = {}
        discovery_successes = 0
        try:
            with requests.Session() as session:
                for area in AREAS:
                    try:
                        places = discover(session, area, key, pages)
                    except Exception:
                        status["areas"][area] = {"status": "failed", "discovered": 0, "collected": 0}
                        continue
                    discovery_successes += 1
                    counts = {"status": "ok", "discovered": len(places), "collected": 0, "failed": 0}
                    status["areas"][area] = counts
                    for place in places:
                        try:
                            payload = _get_json(session, PUBLIC_PANEL.format(place_id=place["id"]))
                            parsed = parse_public_place(place, area, payload, now)
                            outcomes[place["id"]] = parsed
                            counts["collected"] += parsed is not None
                        except Exception:
                            counts["failed"] += 1
                            status["page_failures"] += 1
                        time.sleep(REQUEST_DELAY)
                    save_status(status)
            if not discovery_successes or not outcomes:
                raise RuntimeError("No public place collection succeeded")
            # Hold only the save lock here, then reload so administrator changes
            # made during network requests are preserved.
            with path.with_suffix(".lock").open("a") as save_lock:
                fcntl.flock(save_lock, fcntl.LOCK_EX)
                current = store.read_catalog()
                merged = merge_results(current, outcomes, now)
                saved = merged.model_copy(update={"revision": current.revision + 1})
                write_json_atomic(saved.model_dump(mode="json"), path.parent, path.name)
            status.update(status="partial" if discovery_successes < len(AREAS) or status["page_failures"] else "ok",
                          last_success_at=now.isoformat(), items=len(saved.items))
        except Exception:
            status["status"] = "failed"
        status["finished_at"] = store.now_kst().isoformat()
        save_status(status)
        return status
