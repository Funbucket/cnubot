import json

import requests
from bs4 import BeautifulSoup as bs


def scrap_menu(url: str, place: str) -> str:
    response = requests.get(url)
    soup = bs(response.content, "html.parser")

    menu_data = {"place": place, "menu": []}

    table = soup.find("table", class_="menu-tbl")

    # 운영일자 추출
    ths = table.find_all("th")
    if len(ths) >= 2:
        # 두번째 th에서 시작일, 마지막 th에서 종료일 추출 (childNodes[2]에 해당)
        start_th = ths[1]
        end_th = ths[-1]
        start_date_raw = (
            start_th.contents[2].strip() if len(start_th.contents) >= 3 else ""
        )
        end_date_raw = end_th.contents[2].strip() if len(end_th.contents) >= 3 else ""
        if start_date_raw and end_date_raw:
            start_parts = start_date_raw.split(".")
            end_parts = end_date_raw.split(".")
            if len(start_parts) == 3 and len(end_parts) == 3:
                # "YYYY.MM.DD" -> "MM/DD"
                menu_date = (
                    f"{start_parts[1]}/{start_parts[2]} ~ {end_parts[1]}/{end_parts[2]}"
                )
            else:
                menu_date = ""
        else:
            menu_date = ""
    else:
        menu_date = ""

    menu_data["date"] = menu_date

    days = ["월", "화", "수", "목", "금", "토"]

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
