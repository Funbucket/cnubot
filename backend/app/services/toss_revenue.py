"""Read-only, cached Toss account performance for the administrator dashboard."""
import asyncio
import os
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from app.services import toss_sharelink as toss

KST = ZoneInfo("Asia/Seoul")
FIELDS = (
    "clickCount", "soldQuantity", "refundedQuantity", "salesAmount",
    "discountAmount", "netPaymentAmount", "expectedCommissionAmount",
    "confirmedCommissionAmount",
)
CACHE_SECONDS = 300
_cache = {}
_lock = threading.Lock()


def date_windows(start: date, end: date):
    """Inclusive, non-overlapping windows within Toss's 31-day limit."""
    while start <= end:
        stop = min(start + timedelta(days=30), end)
        yield start, stop
        start = stop + timedelta(days=1)


def _summary(start, end):
    key = (start, end)
    cached = _cache.get(key)
    if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
        return cached[1]
    params = {"fromDate": start.isoformat(), "toDate": end.isoformat(), "size": 1}
    try:
        body = toss._get_live_sync("/openapi/performance", params)
    except toss.TossSharelinkError as exc:
        if str(exc) not in {"Toss HTTP 401", "UNAUTHORIZED"}:
            raise
        toss._token = None
        body = toss._get_live_sync("/openapi/performance", params)
    summary = body.get("success", {}).get("summary")
    if body.get("resultType") != "SUCCESS" or not isinstance(summary, dict):
        raise toss.TossSharelinkError("INVALID_REVENUE_RESPONSE")
    # Missing fields must never turn a failed/changed response into zero revenue.
    if any(type(summary.get(field)) is not int for field in FIELDS):
        raise toss.TossSharelinkError("INVALID_REVENUE_SUMMARY")
    updated = summary.get("lastUpdatedAt")
    if updated is not None:
        stamp = datetime.fromisoformat(updated)
        updated = (stamp.replace(tzinfo=KST) if stamp.tzinfo is None else stamp).astimezone(KST)
    result = {
        **{field: summary[field] for field in FIELDS},
        "lastUpdatedAt": updated,
        "fetched_at": datetime.now(KST),
    }
    # Bound process memory when many custom date ranges are requested.
    if len(_cache) >= 128:
        del _cache[min(_cache, key=lambda item: _cache[item][0])]
    _cache[key] = (time.monotonic(), result)
    return result


def _report_sync(start, end):
    totals = dict.fromkeys(FIELDS, 0)
    updated, fetched = [], []
    # Serial reads coalesce concurrent requests and respect the partner rate limit.
    with _lock:
        deadline = time.monotonic() + 25
        for index, (first, last) in enumerate(date_windows(start, end)):
            if time.monotonic() >= deadline:
                raise toss.TossSharelinkError("REVENUE_TIMEOUT")
            if index:
                time.sleep(0.12)
            summary = _summary(first, last)
            # summary covers the entire window, independently of item pagination.
            for field in FIELDS:
                totals[field] += summary[field]
            if summary["lastUpdatedAt"]:
                updated.append(summary["lastUpdatedAt"])
            fetched.append(summary["fetched_at"])
    return {
        "status": "ok", "start_date": start, "end_date": end, "summary": totals,
        "last_updated_at": max(updated) if updated else None,
        "fetched_at": min(fetched),
    }


async def get_revenue(start_date=None, end_date=None):
    if not all(os.getenv(key, "").strip() for key in ("TOSS_ACCESS_KEY", "TOSS_SECRET_KEY")):
        return {"status": "not_configured"}
    today = datetime.now(KST).date()
    end = min(end_date or today, today)
    start = start_date
    if start is None:
        from app.database import get_pool

        async with get_pool().acquire() as conn:
            start = await conn.fetchval("""
                SELECT (MIN(created_at) AT TIME ZONE 'Asia/Seoul')::date
                FROM user_events
                WHERE event_name LIKE 'promotion_%' OR event_name = 'commerce_card_click'
            """)
    if start is None:
        return {"status": "no_start_date"}
    if start > end:
        return {"status": "no_period"}
    if (end - start).days >= 31 * 120:
        return {"status": "too_long"}
    try:
        return await asyncio.to_thread(_report_sync, start, end)
    except (toss.TossSharelinkError, requests.RequestException, ValueError, TypeError, AttributeError):
        # Do not expose provider error bodies, credentials, or partial financial totals.
        return {"status": "unavailable"}
