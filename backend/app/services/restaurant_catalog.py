"""Persistent, atomically replaced catalog, with no fabricated seed restaurants."""
import fcntl
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.schemas.restaurants import Catalog, Restaurant
from app.utils.json_files import write_json_atomic

KST = ZoneInfo("Asia/Seoul")
MENU_MAX_AGE = timedelta(days=30)
RATING_MAX_AGE = timedelta(days=7)


def now_kst():
    return datetime.now(KST)


def today_kst():
    return now_kst().date()


def catalog_path():
    return Path(os.getenv("RESTAURANTS_DATA_PATH", str(
        Path(os.getenv("MENU_DATA_DIR", "data")) / "restaurants.json")))


def read_catalog() -> Catalog:
    try:
        return Catalog.model_validate_json(catalog_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Catalog()


def safe_catalog() -> Catalog:
    try:
        return read_catalog()
    except (OSError, ValueError):
        # A damaged operator file must never produce guessed or packaged prices.
        return Catalog()


def save_catalog(catalog: Catalog) -> Catalog:
    path = catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if read_catalog().revision != catalog.revision:
            raise ValueError("다른 창에서 목록이 변경되었습니다. 다시 불러와주세요.")
        saved = catalog.model_copy(update={"revision": catalog.revision + 1})
        write_json_atomic(saved.model_dump(mode="json"), path.parent, path.name)
        return saved


def fresh_meals(item: Restaurant, now: datetime):
    return [meal for meal in item.meals
            if timedelta(0) <= now.date() - meal.checked_on <= MENU_MAX_AGE]


def fresh_rating(item: Restaurant, now: datetime):
    rating = item.rating
    return rating if rating and timedelta(0) <= now - rating.checked_at <= RATING_MAX_AGE else None


def ratings_available(catalog: Catalog, now: datetime):
    return bool(catalog.ratings_enabled and catalog.rating_usage_basis and any(
        item.enabled and fresh_meals(item, now) and fresh_rating(item, now)
        for item in catalog.items))


def entry_enabled():
    # Reveal message buttons only after the operator has registered their utterances.
    return os.getenv("RESTAURANTS_ENABLED", "false").lower() == "true"


def search_places(query: str) -> list[dict]:
    import requests
    key = os.getenv("KAKAO_REST_API_KEY", "")
    if not key:
        raise RuntimeError("장소 검색 키가 설정되지 않았습니다.")
    response = requests.get(
        "https://dapi.kakao.com/v2/local/search/keyword.json",
        headers={"Authorization": "KakaoAK " + key},
        params={"query": query, "category_group_code": "FD6", "size": 5},
        timeout=(2, 3),
    )
    response.raise_for_status()
    # Transient admin assistance only; API search responses are never written to disk.
    fields = ("place_name", "category_name", "road_address_name", "place_url")
    return [{field: item.get(field, "") for field in fields}
            for item in response.json().get("documents", [])]
