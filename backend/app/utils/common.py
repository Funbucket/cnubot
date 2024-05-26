import json
from datetime import datetime

import aiofiles
import pytz
from app.utils import kakao_json_response

SERVER_URL = "http://15.164.169.110"

DAYS_OF_WEEK_KOREAN = ["월", "화", "수", "목", "금", "토", "일"]


PLACE_KOREAN = {
    "dorm": "기숙사",
    "hall_1": "1학생회관",
    "hall_2": "2학생회관",
    "hall_3": "3학생회관",
    "sangrok": "상록회관",
    "life_science": "생활과학대학",
}


def get_current_kr_time():
    KST = pytz.timezone("Asia/Seoul")
    return datetime.now(KST)


def get_menu_by_day(data, day: str):
    day_key = day[0]  # "월요일"에서 "월" 추출
    for day_menu in data["menu"]:
        if day_key in day_menu["day"]:
            return day_menu
    return None


def get_kor_day(weekday_index: int):
    return DAYS_OF_WEEK_KOREAN[weekday_index] + "요일"


def get_today_in_korean():
    today = get_current_kr_time().weekday()
    return get_kor_day(today)


def get_kor_place(place: str):
    return PLACE_KOREAN.get(place)


def get_eng_place(place: str):
    for key, value in PLACE_KOREAN.items():
        if value == place:
            return key
    return place


async def load_data(file_path: str):
    async with aiofiles.open(file_path, "r", encoding="utf-8") as file:
        content = await file.read()
        data = json.loads(content)
    return data


def create_no_menu_response():
    kakao_response = kakao_json_response.KakaoJsonResponse()
    simple_text = kakao_response.create_simple_text("운영 중인 메뉴가 없어요 🥲")
    kakao_response.add_output_to_response(simple_text)
    return kakao_response.get_response()
