import requests
from app.utils import kakao_json_response
from bs4 import BeautifulSoup as bs

CLICKER_URL = "https://clicker.cnu.ac.kr/Clicker/k/"
TIMETABLE_URL = "https://library.cnu.ac.kr/webcontent/info/48"


def create_seats_response():
    response = requests.get(CLICKER_URL)
    soup = bs(response.content.decode("utf8", "replace"), "html.parser")

    table = soup.find("table", {"class": "clicker_libtech_table_list"})
    rows = table.find("tbody").find_all("tr")

    seat_info = []
    for row in rows:
        columns = row.find_all("td")
        location = columns[0].text.strip()
        total_seats = columns[1].text.strip()
        available_seats = columns[2].text.strip()
        status = columns[4].text.strip()

        seat_info.append(
            {
                "location": location,
                "total_seats": total_seats,
                "available_seats": available_seats,
                "status": status,
            }
        )

    kakao_response = kakao_json_response.KakaoJsonResponse()

    if not seat_info:
        kakao_response.add_output_to_response(
            kakao_response.create_simple_text("현재 이용 가능한 좌석 정보가 없습니다.")
        )
    else:
        descriptions = [
            f"📍 {info['location']}\n전체 좌석: {info['total_seats']}\n잔여 좌석: {info['available_seats']}\n상태: {info['status']}\n"
            for info in seat_info
        ]
        kakao_response.add_output_to_response(
            {
                "textCard": kakao_response.create_text_card(
                    title="자석현황",
                    description="\n".join(descriptions),
                    buttons=[
                        {
                            "action": "webLink",
                            "label": "개관시간 보기",
                            "webLinkUrl": f"{TIMETABLE_URL}",
                        }
                    ],
                )
            }
        )

    return kakao_response.get_response()
