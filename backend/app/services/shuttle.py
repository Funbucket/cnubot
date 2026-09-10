from datetime import date, datetime, timedelta

from app.utils import common, kakao_json_response
from app.services.shuttle_calendar import (
    _event_date,
    _calendar_event_on,
    _is_holiday,
    _is_break,
    _next_service_date,
    _non_operation_reason,
)

CNU_SHUTTLE_URL = "https://plus.cnu.ac.kr/html/kr/sub05/sub05_050403.html"
ACADEMIC_CALENDAR_URL = (
    "https://plus.cnu.ac.kr/_prog/academic_calendar/"
    "?site_dvs_cd=kr&menu_dvs_cd=&year={year}"
)


def parse_times(schedule):
    """
    수정된 시간표 구조에 맞게, 단일 노선의 출발 시각 리스트를 반환합니다.
    """
    return {
        route: [{"time": t} for t in data["times"]]
        for route, data in schedule["bus_schedule"].items()
    }


def calculate_bus_times(times, current_kst):
    """
    주어진 출발 시각 리스트에서 현재 기준으로 지난(운행중) 버스와 앞으로 올(대기중) 버스를 계산합니다.
    """

    def get_bus_time(t_str):
        return datetime.strptime(t_str, "%H:%M").replace(
            year=current_kst.year,
            month=current_kst.month,
            day=current_kst.day,
            tzinfo=current_kst.tzinfo,
        )

    times_with_bus_time = [{"time": get_bus_time(bus["time"])} for bus in times]
    first_bus_time = times_with_bus_time[0]["time"]
    last_bus_time = times_with_bus_time[-1]["time"]

    if current_kst < first_bus_time:
        return {
            "status": "before_first",
            "past": [],
            "future": [{"time": first_bus_time.strftime("%H:%M")}],
        }
    if current_kst > last_bus_time + timedelta(minutes=16):
        return {"status": "ended", "past": [], "future": []}

    past_buses = [
        {
            "time": bus["time"].strftime("%H:%M"),
            "minutes_ago": (current_kst - bus["time"]).seconds // 60,
        }
        for bus in times_with_bus_time
        if current_kst - timedelta(minutes=16) <= bus["time"] <= current_kst
    ][:2]

    future_buses = sorted(
        [
            {
                "time": bus["time"].strftime("%H:%M"),
                "minutes_left": (bus["time"] - current_kst).seconds // 60,
            }
            for bus in times_with_bus_time
            if bus["time"] > current_kst
        ],
        key=lambda x: x["minutes_left"],
    )[:2]

    return {"status": "operating", "past": past_buses, "future": future_buses}


def _date_label(target: date) -> str:
    weekdays = "월화수목금토일"
    return f"{target.month}월 {target.day}일 {weekdays[target.weekday()]}요일"


def _first_departure(data: dict) -> str:
    times = [
        time
        for route in data.get("bus_schedule", {}).values()
        for time in route.get("times", [])
    ]
    return min(times, key=lambda value: tuple(int(part) for part in value.split(":"))) if times else "08:30"


def _status_buttons(route: str):
    buttons = []
    if route == "교내 순환":
        buttons.append(
            {
                "action": "webLink",
                "label": "노선·정류장 보기",
                "webLinkUrl": "https://cdn.jsdelivr.net/gh/Funbucket/cnubot@menu-inline-promotion-card/backend/app/static/images/shuttle_route.jpg",
            }
        )
    buttons.append(
        {
            "action": "webLink",
            "label": "학교 공지 보기",
            "webLinkUrl": CNU_SHUTTLE_URL,
        }
    )
    return buttons


def create_nearby_shuttles_response(data):
    current_kst = common.get_current_kr_time()
    today = current_kst.date()
    calendar = data.get("academic_calendar", {})
    reason = _non_operation_reason(calendar, today)
    first_departure = _first_departure(data)
    if reason:
        next_date = _next_service_date(calendar, today)
        kakao_response = kakao_json_response.KakaoJsonResponse()
        kakao_response.add_output_to_response(
            {
                "textCard": kakao_response.create_text_card(
                    title="🚌 오늘은 셔틀 휴무일이에요",
                    description=f"사유: {reason}\n다음 운행: {_date_label(next_date)} {first_departure}",
                    buttons=[
                        {
                            "action": "webLink",
                            "label": "학교 공지 보기",
                            "webLinkUrl": CNU_SHUTTLE_URL,
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

    if all(state["status"] == "ended" for state in result.values()):
        kakao_response.add_output_to_response(
            {
                "textCard": kakao_response.create_text_card(
                    title="🌙 오늘 셔틀 운행이 종료됐어요",
                    description=(
                        f"다음 운행: {_date_label(_next_service_date(calendar, today))} "
                        f"{first_departure}"
                    ),
                    buttons=[
                        {
                            "action": "webLink",
                            "label": "학교 공지 보기",
                            "webLinkUrl": CNU_SHUTTLE_URL,
                        }
                    ],
                )
            }
        )
    else:
        items = [
            kakao_response.create_text_card(
                title=f"{route} 노선",
                description=_route_description(buses),
                buttons=_status_buttons(route),
            )
            for route, buses in result.items()
            if buses["status"] != "ended" or len(result) == 1
        ]
        kakao_response.add_output_to_response(kakao_response.create_carousel(items))

    return kakao_response.get_response()


def _route_description(state: dict) -> str:
    if state["status"] == "before_first":
        return f"🌅 운행 전\n첫차 {state['future'][0]['time']}"
    if state["status"] == "ended":
        return "🌙 운행 종료\n오늘 운행이 끝났어요"
    sections = []
    if state["past"]:
        sections.append(
            f"🚌 운행중 ({len(state['past'])}대)\n"
            + "\n".join(
                f"{bus['time']} 출발 ({bus['minutes_ago']}분 전)"
                for bus in state["past"]
            )
        )
    if state["future"]:
        sections.append(
            f"💤 대기중 ({len(state['future'])}대)\n"
            + "\n".join(
                f"{bus['time']} 출발 ({bus['minutes_left']}분 후)"
                for bus in state["future"]
            )
        )
    return "\n\n".join(sections)
