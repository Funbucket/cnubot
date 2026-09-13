import argparse
from pathlib import Path

from app.scrapers.cnu_food import scrape_mobile_food_menu
from app.scrapers.dorm import scrape_dorm_hours, scrape_dorm_menu
from app.scrapers.settings import DORM_URL, get_mobile_food_url
from app.utils import common
from app.utils.json_files import write_json_atomic as _write_json

SCRAPABLE_PLACES = ["dorm", "hall_2", "hall_3", "sangrok", "life_science"]


def scrape_place(place: str) -> dict:
    if place == "dorm":
        return scrape_dorm_menu(DORM_URL)
    if place in {"hall_2", "hall_3", "sangrok", "life_science"}:
        return scrape_mobile_food_menu(get_mobile_food_url(place), place)
    raise ValueError(f"Unsupported place: {place}")


def save_menu(data: dict, data_dir: Path) -> Path:
    validate_menu_data(data)
    return _write_json(data, data_dir, f"{data['place']}_menu.json")


def save_dorm_hours(data_dir: Path) -> Path:
    """Keep operating hours crawled rather than hardcoded, alongside the weekly menus."""
    hours = scrape_dorm_hours()
    if not hours.get("hours", {}).get("lunch"):
        raise ValueError("Dorm hours are missing lunch")
    return _write_json(hours, data_dir, "dorm_hours.json")


def validate_menu_data(data: dict) -> None:
    place = data.get("place")
    if not place:
        raise ValueError("Menu data is missing place")

    menus = data.get("menu")
    if not isinstance(menus, list) or not menus:
        raise ValueError(f"Menu data for {place} has no menu rows")

    has_items = False
    for day_menu in menus:
        for meal_time in ("breakfast", "lunch", "dinner"):
            for meal in day_menu.get(meal_time, []):
                if meal.get("menu"):
                    has_items = True
                    break
            if has_items:
                break
        if has_items:
            break

    if not has_items:
        raise ValueError(f"Menu data for {place} has no menu items")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scrape CNU cafeteria menu JSON files.")
    parser.add_argument(
        "places",
        nargs="+",
        help="Places to scrape: all, dorm, hall_2, hall_3, sangrok, life_science",
    )
    parser.add_argument(
        "--data-dir",
        default=str(common.MENU_DATA_DIR),
        help="Directory where menu JSON files are written.",
    )
    return parser.parse_args()


def expand_places(places: list[str]) -> list[str]:
    if "all" in places:
        return SCRAPABLE_PLACES
    unknown = sorted(set(places) - set(SCRAPABLE_PLACES))
    if unknown:
        raise ValueError(f"Unsupported place(s): {', '.join(unknown)}")
    return places


def main() -> None:
    args = parse_args()
    data_dir = Path(args.data_dir)
    places = expand_places(args.places)
    for place in places:
        path = save_menu(scrape_place(place), data_dir)
        print(f"saved {place}: {path}")
    if "dorm" in places:
        print(f"saved dorm hours: {save_dorm_hours(data_dir)}")


if __name__ == "__main__":
    main()
