from datetime import datetime

import pendulum

# import pytz

KST = pendulum.timezone("Asia/Seoul")
CURRENT_KR_TIME = datetime.now(KST)
# START_KR_DATE = datetime(2024, 5, 19, tzinfo=KST)
START_KR_DATE = datetime(2024, 5, 19, tzinfo=KST)

today_date_korea = CURRENT_KR_TIME.strftime("%Y.%m.%d")

DORM_URL = "https://dorm.cnu.ac.kr/html/kr/sub03/sub03_0304.html"
HALL_2_URL = f"https://mobileadmin.cnu.ac.kr/food/index.jsp?searchYmd={today_date_korea}&searchLang=OCL04.10&searchView=date&searchCafeteria=OCL03.02&Language_gb=OCL04.10#tmp"
HALL_3_URL = f"https://mobileadmin.cnu.ac.kr/food/index.jsp?searchYmd={today_date_korea}&searchLang=OCL04.10&searchView=date&searchCafeteria=OCL03.03&Language_gb=OCL04.10#tmp"
SANGROK_URL = f"https://mobileadmin.cnu.ac.kr/food/index.jsp?searchYmd={today_date_korea}&searchLang=OCL04.10&searchView=date&searchCafeteria=OCL03.04&Language_gb=OCL04.10#tmp"
LIFE_SCIENCE_URL = f"https://mobileadmin.cnu.ac.kr/food/index.jsp?searchYmd={today_date_korea}&searchLang=OCL04.10&searchView=date&searchCafeteria=OCL03.05&Language_gb=OCL04.10#tmp"
