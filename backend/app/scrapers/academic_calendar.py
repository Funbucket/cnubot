import re
from datetime import date

import requests
from bs4 import BeautifulSoup as bs

ACADEMIC_CALENDAR_URL = (
    "https://plus.cnu.ac.kr/_prog/academic_calendar/"
    "?site_dvs_cd=kr&menu_dvs_cd=&year={year}"
)


def scrape_academic_calendar(year: int) -> dict:
    response = requests.get(ACADEMIC_CALENDAR_URL.format(year=year), timeout=20)
    response.raise_for_status()
    soup = bs(response.content, "html.parser")
    events = []

    for index, month_box in enumerate(soup.select(".calen_box")):
        month_text = month_box.select_one(".fl_month strong")
        if not month_text:
            continue
        month_match = re.search(r"(\d{1,2})", month_text.get_text(" ", strip=True))
        if not month_match:
            continue
        month = int(month_match.group(1))
        for item in month_box.select("li"):
            day_node = item.select_one("strong")
            title_node = item.select_one(".list")
            if not day_node or not title_node:
                continue
            day_text = day_node.get_text(" ", strip=True)
            match = re.match(r"(\d{1,2})\.(\d{1,2})", day_text)
            if not match:
                continue
            start_month, start_day = int(match.group(1)), int(match.group(2))
            end_match = re.search(r"~\s*(\d{1,2})\.(\d{1,2})", day_text)
            end_month = int(end_match.group(1)) if end_match else start_month
            end_day = int(end_match.group(2)) if end_match else start_day
            try:
                start_year = year - 1 if index == 0 and start_month == 12 else year
                start = date(start_year, start_month, start_day)
                end_year = start_year + (1 if end_month < start_month else 0)
                end = date(end_year, end_month, end_day)
            except ValueError:
                continue
            events.append(
                {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "title": title_node.get_text(" ", strip=True),
                }
            )

    if not events:
        raise ValueError(f"No academic calendar events found for {year}")
    return {"year": year, "events": events}
