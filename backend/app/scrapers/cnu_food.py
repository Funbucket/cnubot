import json

import requests
from bs4 import BeautifulSoup as bs


def scrape_mobile_food_menu(url: str, place: str) -> dict:
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    soup = bs(response.content, "html.parser")

    table = soup.find("table", class_="menu-tbl")
    if not table:
        raise ValueError(f"Menu table not found for {place}")

    menu_data = {"place": place, "menu": []}
    menu_data["date"] = _extract_date_range(table)

    days = ["월", "화", "수", "목", "금", "토"]
    trs = table.find("tbody").find_all("tr")

    for i in range(6):
        breakfast, lunch, dinner = [], [], []
        meal_data = [
            (trs[0].find_all("td")[i + 2], "직원", breakfast),
            (trs[1].find_all("td")[i + 1], "학생", breakfast),
            (trs[2].find_all("td")[i + 2], "직원", lunch),
            (trs[3].find_all("td")[i + 1], "학생", lunch),
            (trs[4].find_all("td")[i + 2], "직원", dinner),
            (trs[5].find_all("td")[i + 1], "학생", dinner),
        ]

        for raw_data, meal_type, meal_list in meal_data:
            meal_list.append({"type": meal_type, "menu": _extract_menu_items(raw_data)})

        menu_data["menu"].append(
            {
                "day": days[i],
                "breakfast": breakfast,
                "lunch": lunch,
                "dinner": dinner,
            }
        )

    return menu_data


def scrape_mobile_food_menu_json(url: str, place: str) -> str:
    return json.dumps(scrape_mobile_food_menu(url, place), ensure_ascii=False)


def _extract_date_range(table) -> str:
    ths = table.find_all("th")
    if len(ths) < 2:
        return ""

    start_raw = ths[1].contents[2].strip() if len(ths[1].contents) >= 3 else ""
    end_raw = ths[-1].contents[2].strip() if len(ths[-1].contents) >= 3 else ""
    if not start_raw or not end_raw:
        return ""

    start_parts = start_raw.split(".")
    end_parts = end_raw.split(".")
    if len(start_parts) != 3 or len(end_parts) != 3:
        return ""

    return f"{start_parts[1]}/{start_parts[2]} ~ {end_parts[1]}/{end_parts[2]}"


def _extract_menu_items(raw_data) -> list[str]:
    for h3 in raw_data.find_all("h3", class_="menu-tit03"):
        h3.extract()
    menu = [item.strip() for item in raw_data.find_all(string=True)]
    return [] if "운영안함" in menu else list(filter(bool, menu))
