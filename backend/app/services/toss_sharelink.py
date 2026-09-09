import asyncio
import time
from typing import Any

import requests


class TossSharelinkError(RuntimeError):
    pass


_token: tuple[str, float] | None = None
_best_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_category_best_cache: dict[tuple[int, int], tuple[float, list[dict[str, Any]]]] = {}
_today_deals_cache: tuple[float, list[dict[str, Any]]] | None = None
_category_cache: tuple[float, dict[int, list[str]]] | None = None
_link_cache: dict[tuple[int, str, str], str] = {}


def _config(name: str) -> str:
    import os

    value = os.getenv(name, "").strip()
    if not value:
        raise TossSharelinkError(f"missing configuration: {name}")
    return value


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise TossSharelinkError(f"invalid Toss response: HTTP {response.status_code}") from exc
    if body.get("resultType") == "FAIL":
        error = body.get("error", {})
        raise TossSharelinkError(error.get("errorCode", "TOSS_API_FAILED"))
    if response.status_code >= 400:
        raise TossSharelinkError(f"Toss HTTP {response.status_code}")
    return body


def _access_token_sync() -> str:
    global _token
    now = time.time()
    if _token and _token[1] > now + 60:
        return _token[0]
    response = requests.post(
        "https://oauth2.cert.toss.im/token",
        data={
            "grant_type": "client_credentials",
            "client_id": _config("TOSS_ACCESS_KEY"),
            "client_secret": _config("TOSS_SECRET_KEY"),
            "scope": "sharelink:read sharelink:write",
        },
        timeout=10,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise TossSharelinkError(f"invalid Toss token response: HTTP {response.status_code}") from exc
    token = body.get("access_token")
    if response.status_code >= 400 or not token:
        raise TossSharelinkError("TOSS_TOKEN_FAILED")
    _token = (token, now + int(body.get("expires_in", 3600)))
    return token


def _get_sync(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.get(
        f"https://sharelink.toss.im{path}",
        params=params,
        headers={"Authorization": f"Bearer {_access_token_sync()}"},
        timeout=10,
    )
    return _json(response)


def _post_sync(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        f"https://sharelink.toss.im{path}",
        json=payload,
        headers={"Authorization": f"Bearer {_access_token_sync()}"},
        timeout=10,
    )
    return _json(response)


async def best_selling(size: int = 10) -> list[dict[str, Any]]:
    now = time.time()
    cached = _best_cache.get(size)
    if cached and cached[0] > now:
        return cached[1]
    body = await asyncio.to_thread(_get_sync, "/openapi/products/best-selling", {"size": size})
    items = body.get("success", {}).get("items", [])
    _best_cache[size] = (now + 3600, items)
    return items


async def best_categories(category_id: int, size: int = 30) -> list[dict[str, Any]]:
    key = (int(category_id), int(size))
    now = time.time()
    cached = _category_best_cache.get(key)
    if cached and cached[0] > now:
        return cached[1]
    body = await asyncio.to_thread(
        _get_sync,
        f"/openapi/products/best-categories/{int(category_id)}",
        {"size": size},
    )
    items = body.get("success", {}).get("items", [])
    # Category rankings are refreshed daily according to the ShareLink API.
    _category_best_cache[key] = (now + 86400, items)
    return items


async def today_deals(size: int = 30) -> list[dict[str, Any]]:
    global _today_deals_cache
    now = time.time()
    if _today_deals_cache and _today_deals_cache[0] > now:
        return _today_deals_cache[1]
    body = await asyncio.to_thread(
        _get_sync,
        "/openapi/products/today-deals",
        {"size": size},
    )
    items = body.get("success", {}).get("items", [])
    end_times = [
        item.get("endAt") for item in items if item.get("endAt")
    ]
    # Recheck at least hourly, and never keep a cache beyond the earliest deal end.
    expiry = now + 3600
    if end_times:
        try:
            from datetime import datetime
            earliest = min(datetime.fromisoformat(value).timestamp() for value in end_times)
            expiry = min(expiry, earliest)
        except (TypeError, ValueError):
            pass
    _today_deals_cache = (max(expiry, now + 60), items)
    return items


async def categories() -> dict[int, list[str]]:
    global _category_cache
    now = time.time()
    if _category_cache and _category_cache[0] > now:
        return _category_cache[1]
    body = await asyncio.to_thread(_get_sync, "/openapi/categories")
    flattened: dict[int, list[str]] = {}

    def walk(nodes: list[dict[str, Any]], parent_path: list[str]) -> None:
        for node in nodes:
            path = parent_path + [str(node.get("displayName", ""))]
            category_id = node.get("categoryId")
            if category_id is not None:
                flattened[int(category_id)] = [name for name in path if name]
            walk(node.get("children", []), path)

    walk(body.get("success", {}).get("categories", []), [])
    _category_cache = (now + 86400, flattened)
    return flattened


async def detail(taca_item_id: int) -> dict[str, Any] | None:
    body = await asyncio.to_thread(
        _get_sync,
        "/openapi/products/detail",
        {"tacaItemIds": taca_item_id},
    )
    return next(iter(body.get("success", {}).get("items", [])), None)


async def issue_link(taca_item_id: int) -> str:
    publisher_id = _config("TOSS_PUBLISHER_ID")
    cache_key = (taca_item_id, publisher_id, "")
    if cache_key in _link_cache:
        return _link_cache[cache_key]
    body = await asyncio.to_thread(
        _post_sync,
        "/openapi/links",
        {"tacaItemId": taca_item_id, "publisherId": publisher_id},
    )
    url = body.get("success", {}).get("shortUrl")
    if not url:
        raise TossSharelinkError("TOSS_LINK_URL_MISSING")
    _link_cache[cache_key] = url
    return url
