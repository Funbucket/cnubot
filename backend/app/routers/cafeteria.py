import os

from app.schemas.kakao_request import KakaoRequest
from app.services import cafeteria, experiments, promotions
from app.utils import common, kakao_json_response
from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()


@router.post("/schedule")
async def get_schedule(req: KakaoRequest | None = Body(default=None)):
    """
    return: 식당 시간표 (static meal_schedule.json + 동적 운영 날짜 추가)
    """
    utterance = req.userRequest.utterance.strip() if req else ""
    if _is_dorm_crowding_utterance(utterance):
        return await get_dorm_crowding()

    schedule_data = await common.load_data("/code/app/static/data/meal_schedule.json")
    for cafeteria_data in schedule_data:
        place = cafeteria_data.get("place")
        if not cafeteria_data.get("date"):
            operating_date = await common.get_operating_date_for_place(place)
            if operating_date:
                cafeteria_data["date"] = operating_date

    user_id = _get_user_id(req)
    variant = await experiments.get_active_variant(
        promotions.PROMOTION_EXPERIMENT_KEY, user_id
    )
    if variant:
        await experiments.record_event(
            promotions.PROMOTION_EXPERIMENT_KEY,
            user_id,
            "promotion_exposure",
            {"surface": "schedule"},
        )
    product_key = (variant or {}).get("config", {}).get("product_key")
    response = cafeteria.create_schedule_response(
        schedule_data,
        promotion_product=promotions.get_product(product_key) if variant else None,
    )
    return JSONResponse(response)


@router.post("/menu/today")
async def get_today_menu(req: KakaoRequest):
    """
    req: ex) "기숙사", "제2학생회관", "제3학생회관", "상록회관", "생활과학대학"
    return: 오늘의 메뉴, 요일 퀵리플라이
    """
    utterance = req.userRequest.utterance.strip()
    if _is_dorm_crowding_utterance(utterance):
        return await get_dorm_crowding()

    place = utterance
    current_kst = common.get_current_kr_time()
    today_weekday = current_kst.weekday()  # 0: 월요일, 1: 화요일, ..., 6: 일요일
    kor_day = common.get_kor_day(today_weekday)

    place_key = common.get_eng_place(place)
    data = await common.load_data(str(common.get_menu_data_path(place_key)))
    menu_data = common.get_menu_by_day(data, kor_day)
    if not menu_data:
        raise HTTPException(status_code=404, detail="해당 요일에 메뉴가 없습니다.")

    user_id = _get_user_id(req)
    variant = await experiments.get_active_variant(
        promotions.PROMOTION_EXPERIMENT_KEY, user_id
    )
    if variant:
        await experiments.record_event(
            promotions.PROMOTION_EXPERIMENT_KEY,
            user_id,
            "promotion_exposure",
            {"surface": "menu_today"},
        )
    product_key = (variant or {}).get("config", {}).get("product_key")
    promotion_product = promotions.get_product(product_key)
    response = cafeteria.create_menu_response(
        kor_day, menu_data, place, promotion_product=promotion_product if variant else None
    )
    return JSONResponse(response)


@router.post("/dorm/crowding")
async def get_dorm_crowding():
    """
    return: 기숙사 식당 현재 인원/입장 가능 인원
    """
    try:
        response = await run_in_threadpool(cafeteria.get_dorm_crowding_response)
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="기숙사 혼잡도 정보를 가져오지 못했습니다."
        ) from exc
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

    try:
        data = await common.load_data(str(common.get_menu_data_path(place_key)))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="데이터 파일을 찾을 수 없습니다.")

    menu_data = common.get_menu_by_day(data, kor_day)
    if not menu_data:
        kakao_response = kakao_json_response.KakaoJsonResponse()
        simple_text = kakao_response.create_simple_text("운영 중인 메뉴가 없어요 🥲")
        kakao_response.add_output_to_response(simple_text)

        return kakao_response.get_response()

    user_id = _get_user_id(req)
    variant = await experiments.get_active_variant(
        promotions.PROMOTION_EXPERIMENT_KEY, user_id
    )
    if variant:
        await experiments.record_event(
            promotions.PROMOTION_EXPERIMENT_KEY,
            user_id,
            "promotion_exposure",
            {"surface": "menu_by_day"},
        )
    product_key = (variant or {}).get("config", {}).get("product_key")
    response = cafeteria.create_menu_response(
        kor_day,
        menu_data,
        place,
        promotion_product=promotions.get_product(product_key) if variant else None,
    )
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


def _get_user_id(req: KakaoRequest | None) -> str | None:
    if not req or not req.userRequest.user:
        return None
    return req.userRequest.user.id


def _is_dorm_crowding_utterance(utterance: str) -> bool:
    normalized = utterance.replace(" ", "")
    return "기숙사" in normalized and "혼잡도" in normalized
