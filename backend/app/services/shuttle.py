from datetime import datetime, timedelta

from app.utils import common, kakao_json_response

CNU_SHUTTLE_URL = "https://plus.cnu.ac.kr/html/kr/sub05/sub05_050403.html"


def parse_times(schedule):
    current_date = common.get_current_kr_time().date()
    return {
        route: [
            {
                "bus": key,
                "time": t,
                "operating_period": data["times"][key].get("operating_period"),
            }
            for key, value in data["times"].items()
            if not value.get("operating_period")
            or (
                datetime.strptime(value["operating_period"][0], "%Y-%m-%d").date()
                <= current_date
                <= datetime.strptime(value["operating_period"][1], "%Y-%m-%d").date()
            )
            for period in ["first", "morning", "afternoon", "last"]
            for t in (
                value[period] if isinstance(value[period], list) else [value[period]]
            )
        ]
        for route, data in schedule["bus_schedule"].items()
    }


def calculate_bus_times(times, current_kst):
    def get_bus_time(bus):
        return datetime.strptime(bus["time"], "%H:%M").replace(
            year=current_kst.year,
            month=current_kst.month,
            day=current_kst.day,
            tzinfo=current_kst.tzinfo,
        )

    times_with_bus_time = [
        {"bus": bus["bus"], "time": get_bus_time(bus)} for bus in times
    ]
    first_bus_time = times_with_bus_time[0]["time"]
    last_bus_time = times_with_bus_time[-1]["time"]

    if current_kst < first_bus_time or current_kst > last_bus_time:
        return "운행 종료", []

    past_buses = [
        {
            "bus": bus["bus"],
            "time": bus["time"].strftime("%H:%M"),
            "minutes_ago": (current_kst - bus["time"]).seconds // 60,
        }
        for bus in times_with_bus_time
        if current_kst - timedelta(minutes=10) <= bus["time"] <= current_kst
    ][:2]

    future_buses = sorted(
        [
            {
                "bus": bus["bus"],
                "time": bus["time"].strftime("%H:%M"),
                "minutes_left": (bus["time"] - current_kst).seconds // 60,
            }
            for bus in times_with_bus_time
            if bus["time"] > current_kst
        ],
        key=lambda x: x["minutes_left"],
    )[:2]

    return past_buses, future_buses


def create_nearby_shuttles_response(data):
    current_kst = common.get_current_kr_time()
    # current_kst = datetime(2024, 5, 22, 16, 16, tzinfo=current_kst.tzinfo)  # test time

    if current_kst.weekday() >= 5:
        kakao_response = kakao_json_response.KakaoJsonResponse()
        kakao_response.add_output_to_response(
            {
                "textCard": kakao_response.create_text_card(
                    title="주말은 운영하지 않아요.",
                    description=" ",
                    buttons=[
                        {
                            "action": "webLink",
                            "label": "자세히 보기",
                            "webLinkUrl": f"{CNU_SHUTTLE_URL}",
                        }
                    ],
                )
            }
        )
        return kakao_response.get_response()

    all_route_times = parse_times(data)
    result = {
        route: calculate_bus_times(times, current_kst)
        for route, times in all_route_times.items()
    }

    kakao_response = kakao_json_response.KakaoJsonResponse()

    if all(v == "운행 종료" for v, _ in result.values()):
        kakao_response.add_output_to_response(
            {
                "textCard": kakao_response.create_text_card(
                    title="셔틀 버스 운행이 종료되었습니다.",
                    description=" ",
                    buttons=[
                        {
                            "action": "webLink",
                            "label": "자세히 보기",
                            "webLinkUrl": f"{CNU_SHUTTLE_URL}",
                        }
                    ],
                )
            }
        )
    else:
        items = [
            kakao_response.create_text_card(
                title=f"{route} 노선",
                description=(
                    f"🚌 운행중\n"
                    + "\n".join(
                        [
                            f"{bus['time']} 출발 ({bus['minutes_ago']}분 전)"
                            for bus in buses[0]
                        ]
                    )
                    + "\n\n💤 대기중\n"
                    + "\n".join(
                        [
                            f"{bus['time']} 출발 (앞으로 {bus['minutes_left']}분)"
                            for bus in buses[1]
                        ]
                    )
                ),
                buttons=[
                    {
                        "action": "webLink",
                        "label": "노선표 보기",
                        "webLinkUrl": f"{common.SERVER_URL}/shuttle/images/{route}_routes.jpg",
                    },
                    {
                        "action": "webLink",
                        "label": "자세히 보기",
                        "webLinkUrl": f"{CNU_SHUTTLE_URL}",
                    },
                ],
            )
            for route, buses in result.items()
            if buses != "운행 종료"
        ]
        kakao_response.add_output_to_response(kakao_response.create_carousel(items))

    return kakao_response.get_response()
