import json
import re

import requests
from bs4 import BeautifulSoup as bs

MENU_HEADER_PATTERN = re.compile(
    r"((?:메인|menu|main)\s*\w*)\s*\((?:(\d+)kcal|([^)]*))\)",
    flags=re.IGNORECASE,
)


def scrape_dorm_menu(url: str) -> dict:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = bs(response.content.decode("utf8", "replace"), "html.parser")

    data = {"place": "dorm", "date": _extract_date_range(soup), "menu": []}

    for row in soup.select("table.default_view.diet_table tbody tr"):
        day_cell = row.select_one("td")
        if not day_cell:
            continue
        day = day_cell.text.strip().split("(")[1][:-1]
        data["menu"].append(
            {
                "day": day,
                "breakfast": extract_menus_from_cell(row.select_one("td:nth-of-type(2)")),
                "lunch": extract_menus_from_cell(row.select_one("td:nth-of-type(3)")),
                "dinner": extract_menus_from_cell(row.select_one("td:nth-of-type(4)")),
            }
        )

    return data


def scrape_dorm_menu_json(url: str) -> str:
    return json.dumps(scrape_dorm_menu(url), ensure_ascii=False)


def extract_menus_from_cell(cell) -> list[dict]:
    menu_data = []
    found_types = set()
    current_type = None

    if not cell:
        return menu_data

    for line in cell.stripped_strings:
        match = MENU_HEADER_PATTERN.match(line)
        if match:
            raw_type = match.group(1).strip()
            calorie = match.group(2) or ""
            menu_type = _normalize_menu_type(raw_type)

            if menu_type not in found_types:
                current_type = {
                    "type": menu_type,
                    "calorie": calorie,
                    "menu": [],
                }
                menu_data.append(current_type)
                found_types.add(menu_type)
            else:
                current_type = None

        elif current_type:
            cleaned = re.sub(r"\b\d+(?:,\d+)*\b", "", line).strip(" ,")
            if cleaned:
                current_type["menu"].append(cleaned)

    return menu_data


def _normalize_menu_type(raw_type: str) -> str:
    if re.match(r"^(menu|main)", raw_type, flags=re.IGNORECASE):
        return re.sub(r"^(menu|main)\s*", "메인", raw_type, flags=re.IGNORECASE)
    return raw_type


def _extract_date_range(soup) -> str:
    date_range_element = soup.select_one(".diet_table_top strong")
    date_range_raw = (
        date_range_element.text.strip() if date_range_element else "날짜 정보 없음"
    )
    if date_range_raw == "날짜 정보 없음":
        return date_range_raw

    try:
        start_raw, end_raw = (p.strip() for p in date_range_raw.split("~"))
        _, m1, d1 = start_raw.split("-")
        _, m2, d2 = end_raw.split("-")
        return f"{m1}/{d1} ~ {m2}/{d2}"
    except Exception:
        return date_range_raw
