import re

import requests
from bs4 import BeautifulSoup as bs

SHUTTLE_URL = "https://plus.cnu.ac.kr/html/kr/sub05/sub05_050403.html"


def scrape_shuttle_schedule() -> dict:
    response = requests.get(SHUTTLE_URL, timeout=20)
    response.raise_for_status()
    soup = bs(response.content, "html.parser")
    tables = soup.select("table.content_table")
    if not tables:
        raise ValueError("Shuttle schedule table not found")

    routes = {}
    for row in tables[0].select("tbody tr"):
        cells = row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        route = cells[0].get_text(" ", strip=True).split("(", 1)[0].strip()
        times = []
        for cell in cells[1:]:
            times.extend(re.findall(r"\b\d{1,2}:\d{2}\b", cell.get_text(" ", strip=True)))
        if route and times:
            normalized = {_normalize_time(value) for value in times}
            routes[route] = {"times": sorted(normalized, key=_time_key)}

    if not routes:
        raise ValueError("No shuttle routes found")
    return {"source_url": SHUTTLE_URL, "bus_schedule": routes}


def _time_key(value: str) -> tuple[int, int]:
    hour, minute = value.split(":")
    return int(hour), int(minute)


def _normalize_time(value: str) -> str:
    hour, minute = value.split(":")
    return f"{int(hour):02d}:{int(minute):02d}"
