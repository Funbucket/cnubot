import json
import re

import requests
from airflow.decorators import dag, task
from airflow.models import Param
from bs4 import BeautifulSoup as bs
from settings import CURRENT_KR_TIME, DORM_URL, START_KR_DATE


def extract_menus_from_cell(cell):
    # 셀에서 메뉴 데이터를 추출하고 중복된 메뉴 유형을 필터링합니다. (셀 = td)

    menu_data = []
    found_types = set()

    current_type = None
    for line in cell.stripped_strings:
        if line.startswith("메인"):
            match = re.match(r"(메인\w+)\((\d+)kcal\)", line)

            if match:
                menu_type = match.group(1)
                menu_calorie = match.group(2)

                if menu_type not in found_types:
                    current_type = {
                        "type": menu_type,
                        "calorie": menu_calorie,
                        "menu": [],
                    }
                    menu_data.append(current_type)
                    found_types.add(menu_type)
                else:
                    current_type = None
        elif current_type:
            cleaned_line = re.sub(r"\b\d+(?:,\d+)*\b", "", line).strip(" ,")
            if cleaned_line:
                current_type["menu"].append(cleaned_line)
    return menu_data


@task(task_id="scrap_dorm_menu")
def scrap_menu(dorm_url: str) -> str:
    response = requests.get(dorm_url)
    soup = bs(response.content.decode("utf8", "replace"), "html.parser")

    # 날짜 범위 추출 및 형식 변환
    date_range_element = soup.select_one(".diet_table_top strong")
    date_range_raw = (
        date_range_element.text.strip() if date_range_element else "날짜 정보 없음"
    )
    if date_range_raw != "날짜 정보 없음":
        try:
            parts = date_range_raw.split("~")
            start_date = parts[0].strip()  # 예: "2025-03-03"
            end_date = parts[1].strip()  # 예: "2025-03-09"
            start_parts = start_date.split("-")  # ["2025", "03", "03"]
            end_parts = end_date.split("-")  # ["2025", "03", "09"]
            date_range = (
                f"{start_parts[1]}/{start_parts[2]} ~ {end_parts[1]}/{end_parts[2]}"
            )
        except Exception as e:
            date_range = date_range_raw
    else:
        date_range = date_range_raw

    data = {"place": "dorm", "date": date_range, "menu": []}

    for row in soup.select("table.default_view.diet_table tbody tr"):
        day = row.select_one("td").text.strip().split("(")[1][:-1]
        breakfast_cell = row.select_one("td:nth-of-type(2)")
        lunch_cell = row.select_one("td:nth-of-type(3)")
        dinner_cell = row.select_one("td:nth-of-type(4)")

        day_data = {
            "day": day,
            "breakfast": extract_menus_from_cell(breakfast_cell),
            "lunch": extract_menus_from_cell(lunch_cell),
            "dinner": extract_menus_from_cell(dinner_cell),
        }
        data["menu"].append(day_data)

    return json.dumps(data)


@task(task_id="save_json")
def save_menu(data: str) -> None:
    data_dict = json.loads(data)

    file_path = f"./data/dorm_menu.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=4)


@dag(
    dag_id="ETL_dorm_menu",
    description="ETL dorm menu data pipeline. Extract data in .json format",
    params={
        "DORM_URL": Param(
            title="Dorm URL",
            description="Provide url to Domitory Menu",
            default=DORM_URL,
            type="string",
        ),
    },
    start_date=START_KR_DATE,
    schedule_interval="0 0 * * 0",  # 매주 일요일 자정에 실행
    catchup=True,
)
def pipeline():
    scraped_data = scrap_menu("{{ params.DORM_URL }}")
    save_menu(scraped_data)


dag = pipeline()
