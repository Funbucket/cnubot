from app.scrapers import dorm
from app.services import promotions
from app.utils import common, kakao_json_response

CUISINE_KOREAN = {
    "ramen": "라면",
    "western": "양식",
    "snack": "간식",
    "korean": "한식",
    "japanese": "일식",
    "chinese": "중식",
}

MEAL_TIME_KOREAN = {"breakfast": "🍳 아침", "lunch": "☀️ 점심", "dinner": "🌙 저녁"}

MEAL_TIMES = ("breakfast", "lunch", "dinner")
DORM_HOURS_FILENAME = "dorm_hours.json"
MEAL_SCHEDULE_PATH = "/code/app/static/data/meal_schedule.json"
# textCard 캐러셀의 description은 128자까지 노출된다.
CAROUSEL_DESCRIPTION_LIMIT = 128
CAROUSEL_ROW_SIZE = 3
MENU_OUTPUT_LIMIT = 3

def get_kor_meal_time(meal_time: str):
    return MEAL_TIME_KOREAN.get(meal_time)


def get_kor_cuisine(cuisine: str):
    return CUISINE_KOREAN.get(cuisine)


def create_schedule_response(meal_schedule: list[dict], promotion_product: dict | None = None):
    kakao_response = kakao_json_response.KakaoJsonResponse()

    current_time_kst = common.get_current_kr_time().strftime("%H:%M")

    def format_times(times):
        return (
            "\n".join(
                [
                    # f"{'🟢 ' if time['open'] <= current_time_kst <= time['close'] else ''}{get_kor_meal_time(meal)}: {time['open']}~{time['close']}\n"  # 현재 시간에 이용 가능한 식당 시간
                    f"{get_kor_meal_time(meal)}: {time['open']}~{time['close']}\n"
                    + (f"  {time['extra']}\n" if "extra" in time else "")
                    for meal, time in times.items()
                ]
            )
            + "\n"
        )

    def format_description(cafeteria):
        description = cafeteria.get("extra", "") + "\n\n"
        hours = cafeteria["hours"]

        if cafeteria["place"] == "hall_1":
            for cuisine, times in hours.items():
                description += f"[{get_kor_cuisine(cuisine)}]\n"
                description += format_times(times)
        else:
            description += format_times(hours)

        return (
            description
            if len(description) <= CAROUSEL_DESCRIPTION_LIMIT
            else description[: CAROUSEL_DESCRIPTION_LIMIT - 4] + " ..."
        )

    def create_schedule_buttons(cafeteria):
        place = cafeteria["place"]
        place_name = common.get_kor_place(place)
        buttons = [
            (
                {
                    "action": "webLink",
                    "label": "식단 보기",
                    "webLinkUrl": "https://cnuit.cnu.ac.kr/patis/system/ReportImageViewController.do?platformType=exbuilder&method=view&f0=cooperation&f1=consumer&f2=ocl02&f3=20260820&f4=4BB44F6703C94056A1B18E5F013A066F.png",
                }
                if place == "hall_1"
                else {
                    "action": "message",
                    "label": "식단 보기",
                    "messageText": f"{common.get_today_in_korean()}{place_name}",
                }
            )
        ]
        if place == "dorm":
            buttons.append(
                {
                    "action": "message",
                    "label": "혼잡도 보기",
                    "messageText": "기숙사 혼잡도",
                }
            )
        return buttons

    items = []
    for cafeteria in meal_schedule:
        buttons = create_schedule_buttons(cafeteria)
        items.append(
            kakao_response.create_text_card(
                title=f"{common.get_kor_place(cafeteria.get('place', ''))}"
                + f"{(' (' + cafeteria['date'] + ')') if cafeteria.get('date') else ''}",
                description=format_description(cafeteria).strip(),
                buttons=buttons,
                button_layout="vertical" if len(buttons) > 2 else None,
            )
        )

    # carousel을 3개씩 2개 행으로 출력
    for i in range(0, len(items), 3):
        carousel_items = items[i : i + 3]
        carousel = kakao_response.create_carousel(carousel_items)
        kakao_response.add_output_to_response(carousel)

    kakao_response.add_quick_replies(
        [promotions.create_toss_promotion_quick_reply(kakao_response, promotion_product)]
    )
    response = kakao_response.get_response()
    return response


async def dorm_meal_hours() -> dict:
    """Prefer the crawled dorm hours; fall back to the bundled schedule."""
    try:
        crawled = await common.load_data(str(common.MENU_DATA_DIR / DORM_HOURS_FILENAME))
        if crawled.get("hours"):
            return crawled["hours"]
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        pass
    schedule = await common.load_data(MEAL_SCHEDULE_PATH)
    for entry in schedule:
        if entry.get("place") == "dorm":
            return entry.get("hours") or {}
    return {}


def is_meal_time_over(hours: dict, meal_time: str, now=None) -> bool:
    """Tell whether a meal's serving window has already closed today."""
    close = (hours.get(meal_time) or {}).get("close")
    if not close:
        return False
    try:
        closing_hour, closing_minute = (int(part) for part in close.split(":"))
    except ValueError:
        return False
    now = now or common.get_current_kr_time()
    return (now.hour, now.minute) > (closing_hour, closing_minute)


def _create_menu_text_card(kakao_response, day_label: str, meal_time: str, meal: dict):
    return kakao_response.create_text_card(
        title=f"{day_label} • {get_kor_meal_time(meal_time)} • {meal['type']}",
        description="{}{}".format(
            (f"💰 {meal['price']:,}원\n\n" if meal.get("price") is not None else "")
            + (
                f"칼로리: {meal['calorie']} kcal\n\n"
                if "calorie" in meal and meal["calorie"]
                else ""
            ),
            "\n".join(meal["menu"]),
        ),
        buttons=[
            {"label": "식단 공유하기", "action": "share"},
        ],
        button_layout="vertical",
    )


def _build_meal_rows(kakao_response, day_label: str, menu_data: dict) -> dict[str, list[list]]:
    """Split each meal into carousel-sized rows, keyed by the meal they belong to."""
    rows_by_meal = {}
    for meal_time in MEAL_TIMES:
        items = [
            _create_menu_text_card(kakao_response, day_label, meal_time, meal)
            for meal in menu_data[meal_time]
            if meal["menu"]
        ]
        rows_by_meal[meal_time] = [
            items[start : start + CAROUSEL_ROW_SIZE]
            for start in range(0, len(items), CAROUSEL_ROW_SIZE)
        ]
    return rows_by_meal


def create_menu_response(
    day: str,
    menu_data: dict,
    place: str,
    promotion_product: dict | None = None,
    promotion_click_url: str | None = None,
    inline_product_output: dict | None = None,
):
    kakao_response = kakao_json_response.KakaoJsonResponse()

    today_kor = common.get_today_in_korean()
    day_label = "오늘" if day == today_kor else day
    rows_by_meal = _build_meal_rows(kakao_response, day_label, menu_data)
    row_count = sum(len(rows) for rows in rows_by_meal.values())

    # 운영하지 않는 끼니 자리가 남을 때만 상품 카드를 그 자리에 넣는다.
    # 끼니 행 사이에 카드를 끼우면 메뉴를 비집는 모양이 되므로 하지 않는다.
    # 인라인 상품은 진입 버튼을 대체하므로 두 진입점을 함께 띄우지 않는다.
    product_output = None
    if inline_product_output and row_count < MENU_OUTPUT_LIMIT:
        product_output = inline_product_output
    else:
        # 상품 카드가 들어갈 자리가 없으면 기존 진입 버튼으로 되돌린다.
        # 점심 첫 번째 메뉴 카드에만 간식 특가 버튼을 노출합니다.
        lunch_rows = rows_by_meal["lunch"]
        if lunch_rows:
            lunch_rows[0][0]["buttons"].append(
                promotions.create_toss_promotion_button(
                    promotion_product,
                    promotion_click_url,
                    label=(
                        promotions.TOSS_DORM_MENU_BUTTON_LABEL
                        if common.get_eng_place(place) == "dorm"
                        else promotions.TOSS_LIVING_MENU_BUTTON_LABEL
                    ),
                )
            )
            lunch_rows[0][0]["buttonLayout"] = "vertical"

    placed = False
    for meal_time in MEAL_TIMES:
        if rows_by_meal[meal_time]:
            for items in rows_by_meal[meal_time]:
                kakao_response.add_output_to_response(kakao_response.create_carousel(items))
        elif product_output and not placed:
            # 비어 있는 끼니 자리를 그대로 물려받아 아침·점심·저녁 순서를 유지한다.
            kakao_response.add_output_to_response(product_output)
            placed = True

    return _finish_menu_response(kakao_response, day, place, today_kor)


def _finish_menu_response(kakao_response, day: str, place: str, today_kor: str):
    quick_replies = [
        kakao_response.create_quick_reply(
            label=(f"• {weekday}" if f"{weekday}요일" == today_kor else weekday),
            message_text=f"{weekday}요일{place}",
        )
        for weekday in common.DAYS_OF_WEEK_KOREAN
    ]

    response = kakao_response.add_quick_replies(quick_replies).get_response()

    if not response["template"]["outputs"]:
        simple_text = kakao_response.create_simple_text("운영 중인 메뉴가 없어요 🥲")
        kakao_response.add_output_to_response(simple_text)

    return response




def create_dorm_crowding_response(crowding: dict):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    current = crowding["current"]
    available = crowding["available"]
    capacity = crowding["capacity"]
    chart = crowding.get("chart", [])
    updated_at = common.get_current_kr_time().strftime("%H:%M:%S")
    occupancy_rate = _calculate_occupancy_rate(current, capacity)

    description = (
        f"현재인원: {current}명\n"
        f"입장가능: {available}명\n"
        f"수용가능: {capacity}명\n"
        f"혼잡률: {_create_progress_bar(occupancy_rate)} {occupancy_rate}%\n"
        f"조회시각: {updated_at}"
    )
    if chart:
        description += "\n\n최근 추이(40분 전 → 현재)\n"
        description += f"{_create_sparkline(chart)}\n"
        description += f"{chart[0]}명 → {chart[-1]}명"

    card = kakao_response.create_text_card(
        title="기숙사 식당 혼잡도",
        description=description,
        buttons=[
            {
                "action": "webLink",
                "label": "원본 보기",
                "webLinkUrl": "https://dorm.cnu.ac.kr/intranet/public/cafe_inwon.php",
            },
            {
                "action": "message",
                "label": "다시 조회",
                "messageText": "기숙사 혼잡도",
            },
        ],
    )
    return kakao_response.add_output_to_response({"textCard": card}).get_response()


def get_dorm_crowding_response():
    crowding = dorm.scrape_dorm_crowding()
    return create_dorm_crowding_response(crowding)


def _calculate_occupancy_rate(current: int, capacity: int) -> int:
    if capacity <= 0:
        return 0
    return round(current / capacity * 100)


def _create_progress_bar(rate: int, width: int = 10) -> str:
    filled = round(width * rate / 100)
    return "█" * filled + "░" * (width - filled)


def _create_sparkline(values: list[int]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    if not values:
        return ""

    max_value = max(values)
    if max_value <= 0:
        return blocks[0] * len(values)

    return "".join(
        blocks[round((value / max_value) * (len(blocks) - 1))] for value in values
    )
