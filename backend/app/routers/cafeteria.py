import os

from app.schemas.kakao_request import KakaoRequest
from app.services import cafeteria
from app.utils import common, kakao_json_response
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()


@router.post("/schedule")
async def get_schedule():
    """
    return: 식당 시간표
    """
    schedule_data = await common.load_data("/opt/airflow/data/meal_schedule.json")
    response = cafeteria.create_schedule_response(schedule_data)
    return JSONResponse(response)


@router.post("/menu/today")
async def get_today_menu(req: KakaoRequest):
    """
    req: ex) "기숙사", "제2학생회관", "제3학생회관", "상록회관", "생활과학대학"
    return: 오늘의 메뉴, 요일 퀵리플라이
    """
    place = req.userRequest.utterance.strip()
    current_kst = common.get_current_kr_time()
    today_weekday = current_kst.weekday()  # 0: 월요일, 1: 화요일, ..., 6: 일요일
    kor_day = common.get_kor_day(today_weekday)

    place_key = common.get_eng_place(place)
    data_path = f"/opt/airflow/data/{place_key}_menu.json"
    data = await common.load_data(data_path)
    menu_data = common.get_menu_by_day(data, kor_day)
    if not menu_data:
        raise HTTPException(status_code=404, detail="해당 요일에 메뉴가 없습니다.")

    response = cafeteria.create_menu_response(kor_day, menu_data, place)
    return JSONResponse(response)


@router.post("/menu/day")
async def get_menu_by_day(req: KakaoRequest):
    """
    req: ex) "월요일기숙사", "월요일제2학생회관"
    return: 요청한 요일의 메뉴
    """
    utterance = req.userRequest.utterance.strip()  # 예: "월요일기숙사"
    kor_day = utterance[:3]  # 예: "월요일"
    place = utterance[3:]  # 예: "기숙사"

    place_key = common.get_eng_place(place)
    data_path = f"/opt/airflow/data/{place_key}_menu.json"

    try:
        data = await common.load_data(data_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="데이터 파일을 찾을 수 없습니다.")

    menu_data = common.get_menu_by_day(data, kor_day)
    if not menu_data:
        kakao_response = kakao_json_response.KakaoJsonResponse()
        simple_text = kakao_response.create_simple_text("운영 중인 메뉴가 없어요 🥲")
        kakao_response.add_output_to_response(simple_text)

        return kakao_response.get_response()

    response = cafeteria.create_menu_response(kor_day, menu_data, place)
    return JSONResponse(response)


@router.get("/images/{image_name}")
async def get_image(image_name: str):
    """
    image_name: 이미지 파일 이름 (예: hall_1_menu.png)
    return: 이미지 파일
    """
    file_path = f"app/static/images/{image_name}"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
