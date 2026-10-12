"""Check the stored week and recover it without replacing good data on failure."""
import fcntl
import json
from datetime import date
from pathlib import Path

from app.jobs.scrape_menus import save_menu
from app.scrapers.dorm import is_current_week_dorm_menu, scrape_current_week_dorm_menu
from app.scrapers.settings import DORM_URL_TEMPLATE
from app.utils import common


class DormMenuUnavailable(ValueError):
    pass


def read_current_menu(data_dir: Path, today: date | None = None) -> dict:
    try:
        data = json.loads((data_dir / "dorm_menu.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DormMenuUnavailable("Dorm menu file is missing or invalid") from exc
    if not is_current_week_dorm_menu(data, today):
        raise DormMenuUnavailable("Dorm menu is stale or incomplete")
    return data


def ensure_current_menu(
    data_dir: Path | None = None, today: date | None = None, *, force: bool = False
) -> dict:
    data_dir = Path(data_dir) if data_dir is not None else common.MENU_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    with (data_dir / ".dorm_menu.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not force:
            try:
                return read_current_menu(data_dir, today)
            except DormMenuUnavailable:
                pass
        data = scrape_current_week_dorm_menu(DORM_URL_TEMPLATE, today=today)
        if not is_current_week_dorm_menu(data, today):
            raise DormMenuUnavailable("Fetched dorm menu is stale or incomplete")
        save_menu(data, data_dir)
        return read_current_menu(data_dir, today)
