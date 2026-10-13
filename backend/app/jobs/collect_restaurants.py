"""Refresh restaurant menus and aggregate ratings outside Kakao requests."""
import argparse
import logging
import time
from datetime import datetime, timedelta

from app.scrapers.restaurants import AREAS, COLLECT_INTERVAL, collect, read_status
from app.services.restaurant_catalog import now_kst

logger = logging.getLogger(__name__)


def due(now, status):
    areas = status.get("areas")
    if not isinstance(areas, dict) or not set(AREAS).issubset(areas):
        # A newly introduced district must not wait for the old six-hour window.
        return True
    try:
        state = status.get("status")
        if state == "running":
            marker, interval = status.get("started_at"), timedelta(minutes=15)
        elif state in {"failed", "partial"}:
            marker, interval = (status.get("finished_at") or status.get("started_at")
                                or status.get("last_success_at")), timedelta(minutes=30)
        else:
            marker, interval = status.get("last_success_at"), COLLECT_INTERVAL
        last = datetime.fromisoformat(marker or "")
        if last.tzinfo is None:
            return True
        return now - last >= interval
    except (KeyError, TypeError, ValueError):
        return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--pages", type=int, default=3, choices=range(1, 4))
    args = parser.parse_args()
    while True:
        if args.once or due(now_kst(), read_status()):
            try:
                status = collect(args.pages)
                logger.info("Restaurant collection: %s; items=%d; page_failures=%d",
                            status.get("status"), status.get("items", 0), status.get("page_failures", 0))
            except Exception:
                logger.error("Restaurant collection failed; existing catalog retained")
                status = {"status": "failed"}
            if args.once:
                return 1 if status.get("status") == "failed" else 0
        if args.once:
            return 0
        time.sleep(300 - time.time() % 300)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
