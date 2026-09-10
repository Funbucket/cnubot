import json
import re

import requests
from bs4 import BeautifulSoup as bs

DORM_CROWDING_URL = "https://dorm.cnu.ac.kr/intranet/public/ajax_cafe_inwon.php"
DORM_HOURS_URL = "https://dorm.cnu.ac.kr/html/kr/sub04/sub04_040301.html"
DORM_HOURS_MEAL_TIMES = {"아침": "breakfast", "점심": "lunch", "저녁": "dinner"}
HOURS_PATTERN = re.compile(r"(\d{1,2}:\d{2})\s*~\s*(\d{1,2}:\d{2})")
HOURS_NOTE_ABBREVIATIONS = (
    ("토/일요일 및 공휴일", "주말·공휴일"),
    ("토요일/일요일 및 공휴일", "주말·공휴일"),
    ("주말 및 공휴일", "주말·공휴일"),
    ("방학기간은", "방학"),
    ("방학기간", "방학"),
)
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


def scrape_dorm_hours(url: str = DORM_HOURS_URL) -> dict:
    """Scrape the dorm cafeteria operating hours so they are not hardcoded."""
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = bs(response.content.decode("utf8", "replace"), "html.parser")

    hours = {}
    for item in soup.select("ul.mealPlan-wrap li"):
        title = item.select_one("strong.tit")
        time_text = item.select_one("span.txt")
        if not title or not time_text:
            continue
        meal_time = DORM_HOURS_MEAL_TIMES.get(title.text.strip())
        matched = HOURS_PATTERN.search(time_text.text)
        if not meal_time or not matched:
            continue
        entry = {"open": matched.group(1), "close": matched.group(2)}
        notes = [
            compact_hours_note(note.text)
            for note in item.select("p.txt-check")
            if _note_adds_information(note.text, entry)
        ]
        if notes:
            entry["extra"] = " / ".join(notes)
        hours[meal_time] = entry

    if not hours:
        raise ValueError("Could not find dorm operating hours")
    return {"place": "dorm", "hours": hours}


def _note_adds_information(note: str, entry: dict) -> bool:
    """Drop notes that just repeat the main window — the schedule card is tight."""
    text = note.strip()
    if not text:
        return False
    matched = HOURS_PATTERN.search(text)
    return not matched or (matched.group(1), matched.group(2)) != (entry["open"], entry["close"])


def compact_hours_note(note: str) -> str:
    text = " ".join(note.split())
    for verbose, short in HOURS_NOTE_ABBREVIATIONS:
        text = text.replace(verbose, short)
    return text.strip(" :")


def scrape_dorm_crowding(url: str = DORM_CROWDING_URL) -> dict:
    inwon_response = requests.get(url, params={"mode": "inwon"}, timeout=10)
    inwon_response.raise_for_status()
    chart_response = requests.get(url, params={"mode": "chart_data"}, timeout=10)
    chart_response.raise_for_status()

    current, available = _parse_inwon(inwon_response.text)
    chart = _parse_chart_data(chart_response.text)
    capacity = current + available

    return {
        "current": current,
        "available": available,
        "capacity": capacity,
        "chart": chart,
    }


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


def _parse_inwon(text: str) -> tuple[int, int]:
    values = text.strip().split("|")
    if len(values) != 2:
        raise ValueError("기숙사 혼잡도 인원 형식이 올바르지 않습니다.")
    return int(values[0]), int(values[1])


def _parse_chart_data(text: str) -> list[int]:
    if not text.strip():
        return []
    return [int(value) for value in text.strip().split(",") if value.strip()]
