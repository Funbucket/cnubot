from datetime import datetime

import pytz

KST = pytz.timezone("Asia/Seoul")

DORM_URL = "https://dorm.cnu.ac.kr/html/kr/sub03/sub03_0304.html"

MOBILE_FOOD_URLS = {
    "hall_2": (
        "https://mobileadmin.cnu.ac.kr/food/index.jsp"
        "?searchYmd={date}&searchLang=OCL04.10&searchView=date"
        "&searchCafeteria=OCL03.02&Language_gb=OCL04.10#tmp"
    ),
    "hall_3": (
        "https://mobileadmin.cnu.ac.kr/food/index.jsp"
        "?searchYmd={date}&searchLang=OCL04.10&searchView=date"
        "&searchCafeteria=OCL03.03&Language_gb=OCL04.10#tmp"
    ),
    "sangrok": (
        "https://mobileadmin.cnu.ac.kr/food/index.jsp"
        "?searchYmd={date}&searchLang=OCL04.10&searchView=date"
        "&searchCafeteria=OCL03.04&Language_gb=OCL04.10#tmp"
    ),
    "life_science": (
        "https://mobileadmin.cnu.ac.kr/food/index.jsp"
        "?searchYmd={date}&searchLang=OCL04.10&searchView=date"
        "&searchCafeteria=OCL03.05&Language_gb=OCL04.10#tmp"
    ),
}


def today_date_korea() -> str:
    return datetime.now(KST).strftime("%Y.%m.%d")


def get_mobile_food_url(place: str) -> str:
    return MOBILE_FOOD_URLS[place].format(date=today_date_korea())
