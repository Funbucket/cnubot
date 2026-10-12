"""Check dorm menus every 15 minutes from Sunday 19:00 through Monday 09:00 KST."""
import logging
import time
from datetime import datetime, time as wall_time
from zoneinfo import ZoneInfo

from app.services.dorm_menu import ensure_current_menu

logger = logging.getLogger(__name__)


def in_check_window(now: datetime) -> bool:
    now = now.astimezone(ZoneInfo("Asia/Seoul"))
    return (
        now.weekday() == 6 and now.time() >= wall_time(19)
        or now.weekday() == 0 and now.time() < wall_time(9, 1)
    )


def check_current_menu(now: datetime) -> dict | None:
    if not in_check_window(now):
        return None
    return ensure_current_menu(today=now.astimezone(ZoneInfo("Asia/Seoul")).date())


def main():
    logger.info("Dorm menu checks scheduled: Sunday 19:00–Monday 09:00 KST, every 15 minutes")
    while True:
        try:
            data = check_current_menu(datetime.now(ZoneInfo("Asia/Seoul")))
            if data is not None:
                logger.info("Dorm menu verified: %s", data["date"])
        except Exception:
            # Do not print request URLs, environment values or operational paths.
            logger.error("Dorm menu verification/recovery failed; retrying in 15 minutes")
        # Align to :00/:15/:30/:45 so Monday's final check runs at 09:00.
        time.sleep(900 - time.time() % 900)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
