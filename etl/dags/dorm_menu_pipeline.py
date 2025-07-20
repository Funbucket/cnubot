import json
import re

import requests
from airflow.decorators import dag, task
from airflow.models import Param
from bs4 import BeautifulSoup as bs
from settings import CURRENT_KR_TIME, DORM_URL, START_KR_DATE

# '메인X' 또는 'MainX' 헤더를 매칭 (대소문자 구분 없이)
MENU_HEADER_PATTERN = re.compile(
    r"((?:메인|Main|MAIN)\w*)\((\d+)kcal\)", flags=re.IGNORECASE
)


def extract_menus_from_cell(cell):
    """
    td 셀에서 메뉴 데이터를 추출.
    '메인A', '메인B', '메인C' 등으로 menu_type을 저장합니다.
    """
    menu_data = []
    found_types = set()
    current_type = None

    for line in cell.stripped_strings:
        match = MENU_HEADER_PATTERN.match(line)
        if match:
            raw_type = match.group(1)  # e.g. "메인A" or "MainA"
            calorie = match.group(2)  # e.g. "780"

            # 영어 'MainX' → 한국어 '메인X' 로 통일
            if re.match(r"^Main", raw_type, flags=re.IGNORECASE):
                menu_type = re.sub(r"^Main", "메인", raw_type, flags=re.IGNORECASE)
            else:
                menu_type = raw_type  # 이미 '메인X' 형태

            # 중복된 타입 한 번만 추가
            if menu_type not in found_types:
                current_type = {
                    "type": menu_type,  # e.g. "메인A", "메인C"
                    "calorie": calorie,
                    "menu": [],
                }
                menu_data.append(current_type)
                found_types.add(menu_type)
            else:
                current_type = None

        elif current_type:
            # 숫자(알러지 코드 등) 제거, 앞뒤 쉼표·공백 정리
            cleaned = re.sub(r"\b\d+(?:,\d+)*\b", "", line).strip(" ,")
            if cleaned:
                current_type["menu"].append(cleaned)

    return menu_data


@task(task_id="scrap_dorm_menu")
def scrap_menu(dorm_url: str) -> str:
    response = requests.get(dorm_url)
    soup = bs(response.content.decode("utf8", "replace"), "html.parser")

    # 날짜 범위 추출 및 변환: YYYY-MM-DD → MM/DD ~ MM/DD
    date_range_element = soup.select_one(".diet_table_top strong")
    date_range_raw = (
        date_range_element.text.strip() if date_range_element else "날짜 정보 없음"
    )
    if date_range_raw != "날짜 정보 없음":
        try:
            start_raw, end_raw = (p.strip() for p in date_range_raw.split("~"))
            y1, m1, d1 = start_raw.split("-")
            y2, m2, d2 = end_raw.split("-")
            date_range = f"{m1}/{d1} ~ {m2}/{d2}"
        except Exception:
            date_range = date_range_raw
    else:
        date_range = date_range_raw

    data = {"place": "dorm", "date": date_range, "menu": []}

    for row in soup.select("table.default_view.diet_table tbody tr"):
        day = row.select_one("td").text.strip().split("(")[1][:-1]
        breakfast = extract_menus_from_cell(row.select_one("td:nth-of-type(2)"))
        lunch = extract_menus_from_cell(row.select_one("td:nth-of-type(3)"))
        dinner = extract_menus_from_cell(row.select_one("td:nth-of-type(4)"))
        data["menu"].append(
            {
                "day": day,
                "breakfast": breakfast,
                "lunch": lunch,
                "dinner": dinner,
            }
        )

    return json.dumps(data, ensure_ascii=False)


@task(task_id="save_json")
def save_menu(data: str) -> None:
    data_dict = json.loads(data)
    with open("./data/dorm_menu.json", "w", encoding="utf-8") as f:
        json.dump(data_dict, f, ensure_ascii=False, indent=4)


@dag(
    dag_id="ETL_dorm_menu",
    description="ETL dorm menu data pipeline. Extract data in .json format",
    params={
        "DORM_URL": Param(
            title="Dorm URL",
            description="Provide url to Dormitory Menu",
            default=DORM_URL,
            type="string",
        ),
    },
    start_date=START_KR_DATE,
    schedule_interval="0 0 * * 0",  # 매주 일요일 자정 실행
    catchup=True,
)
def pipeline():
    scraped = scrap_menu("{{ params.DORM_URL }}")
    save_menu(scraped)


dag = pipeline()
