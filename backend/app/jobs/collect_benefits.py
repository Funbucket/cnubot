"""Refresh public school notices every six hours; retry failures in 15 minutes."""
import argparse
import logging
import time
from datetime import datetime, timedelta

from app.scrapers.benefits import SOURCES, scrape
from app.utils.benefits_data import KST, data_path, read_snapshot

logger = logging.getLogger(__name__)


def due(now: datetime, snapshot: dict) -> bool:
    for category in SOURCES:
        source = snapshot.get("sources", {}).get(category, {})
        if source.get("status") != "ok" or source.get("detail_failures"):
            return True
        try:
            if now - datetime.fromisoformat(source["last_success_at"]) >= timedelta(hours=6):
                return True
        except (KeyError, TypeError, ValueError):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--pages", type=int, default=3, choices=range(1, 6))
    args = parser.parse_args()
    while True:
        try:
            snapshot = read_snapshot(data_path())
            if args.once or due(datetime.now(KST), snapshot):
                count = scrape(pages=args.pages, reuse_recent=not args.once)
                logger.info("School notices saved: %d", count)
        except Exception:
            logger.error("School notice collection failed; last snapshot retained")
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        time.sleep(900 - time.time() % 900)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
