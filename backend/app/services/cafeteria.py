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


def get_kor_meal_time(meal_time: str):
    return MEAL_TIME_KOREAN.get(meal_time)


def get_kor_cuisine(cuisine: str):
    return CUISINE_KOREAN.get(cuisine)


def create_schedule_response(meal_schedule: dict):
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

        return description if len(description) <= 100 else description[:97] + " ..."

    items = [
        kakao_response.create_text_card(
            title=common.get_kor_place(cafeteria["place"]),
            description=format_description(cafeteria).strip(),
            buttons=[
                (
                    {
                        "action": "webLink",
                        "label": "식단 보기",
                        "webLinkUrl": f"{common.SERVER_URL}/cafeteria/images/hall_1_menu.png",
                    }
                    if cafeteria["place"] == "hall_1"
                    else {
                        "action": "message",
                        "label": "식단 보기",
                        "messageText": f"{common.get_today_in_korean()}{common.get_kor_place(cafeteria['place'])}",
                    }
                ),
            ],
        )
        for cafeteria in meal_schedule
    ]

    # carousel을 3개씩 2개 행으로 출력
    for i in range(0, len(items), 3):
        carousel_items = items[i : i + 3]
        carousel = kakao_response.create_carousel(carousel_items)
        kakao_response.add_output_to_response(carousel)

    response = kakao_response.get_response()
    return response


def create_menu_response(day: str, menu_data: dict, place: str):
    kakao_response = kakao_json_response.KakaoJsonResponse()

    today_kor = common.get_today_in_korean()
    day_label = "오늘" if day == today_kor else day

    for meal_time in ["breakfast", "lunch", "dinner"]:
        items = [
            kakao_response.create_text_card(
                title=f"{day_label} • {get_kor_meal_time(meal_time)} • {meal['type']}",
                description="{}{}".format(
                    (
                        f"칼로리: {meal['calorie']} kcal\n\n"
                        if "calorie" in meal and meal["calorie"]
                        else ""
                    ),
                    "\n".join(meal["menu"]),
                ),
                buttons=[{"label": "식단 공유하기", "action": "share"}],
            )
            for meal in menu_data[meal_time]
            if meal["menu"]
        ]

        # carousel을 3개씩 2개 행으로 출력
        for i in range(0, len(items), 3):
            carousel_items = items[i : i + 3]
            carousel = kakao_response.create_carousel(carousel_items)
            kakao_response.add_output_to_response(carousel)

    quick_replies = [
        kakao_response.create_quick_reply(label=day, message_text=f"{day}요일{place}")
        for day in common.DAYS_OF_WEEK_KOREAN
    ]

    response = kakao_response.add_quick_replies(quick_replies).get_response()

    if not response["template"]["outputs"]:
        simple_text = kakao_response.create_simple_text("운영 중인 메뉴가 없어요 🥲")
        kakao_response.add_output_to_response(simple_text)

    return response
