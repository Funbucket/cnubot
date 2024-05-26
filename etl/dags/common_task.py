import json

import requests
from bs4 import BeautifulSoup as bs


def scrap_menu(url: str, place: str) -> str:
    response = requests.get(url)
    soup = bs(response.content, "html.parser")

    menu_data = {"place": place, "menu": []}
    days = ["월", "화", "수", "목", "금", "토"]

    table = soup.find("table", class_="menu-tbl")
    tbody = table.find("tbody")
    trs = tbody.find_all("tr")

    for i in range(6):
        day_menu = {"day": days[i]}
        breakfast, lunch, dinner = [], [], []

        meal_data = [
            (trs[0].find_all("td")[i + 2], "직원", breakfast),
            (trs[1].find_all("td")[i + 1], "학생", breakfast),
            (trs[2].find_all("td")[i + 2], "직원", lunch),
            (trs[3].find_all("td")[i + 1], "학생", lunch),
            (trs[4].find_all("td")[i + 2], "직원", dinner),
            (trs[5].find_all("td")[i + 1], "학생", dinner),
        ]

        def process_data(raw_data):
            for h3 in raw_data.find_all("h3", class_="menu-tit03"):
                h3.extract()
            menu = [item.strip() for item in raw_data.find_all(text=True)]
            return [] if "운영안함" in menu else list(filter(bool, menu))

        for raw_data, meal_type, meal_list in meal_data:
            meal_list.append({"type": meal_type, "menu": process_data(raw_data)})

        day_menu.update({"breakfast": breakfast, "lunch": lunch, "dinner": dinner})
        menu_data["menu"].append(day_menu)

    return json.dumps(menu_data, ensure_ascii=False)


def save_json(data: str, file_path: str) -> None:
    data_dict = json.loads(data)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=4)
