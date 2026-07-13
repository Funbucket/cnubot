import argparse
import json
from pathlib import Path

from app.scrapers.cnu_food import scrape_mobile_food_menu
from app.scrapers.dorm import scrape_dorm_menu
from app.scrapers.settings import DORM_URL, get_mobile_food_url
from app.utils import common

SCRAPABLE_PLACES = ["dorm", "hall_2", "hall_3", "sangrok", "life_science"]


def scrape_place(place: str) -> dict:
    if place == "dorm":
        return scrape_dorm_menu(DORM_URL)
    if place in {"hall_2", "hall_3", "sangrok", "life_science"}:
        return scrape_mobile_food_menu(get_mobile_food_url(place), place)
    raise ValueError(f"Unsupported place: {place}")


def save_menu(data: dict, data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    place = data["place"]
    path = data_dir / f"{place}_menu.json"
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=4),
        encoding="utf-8",
    )
    return path


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
    for place in expand_places(args.places):
        path = save_menu(scrape_place(place), data_dir)
        print(f"saved {place}: {path}")


if __name__ == "__main__":
    main()
