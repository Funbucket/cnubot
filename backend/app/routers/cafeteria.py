import os

from app.schemas.kakao_request import KakaoRequest
from app.services import cafeteria, cafeteria_favorites, menu_reactions
from app.utils import common, kakao_json_response
from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()


@router.post("/schedule")
async def get_schedule(req: KakaoRequest | None = Body(default=None)):
    """
    return: 식당 시간표 (static meal_schedule.json + 동적 운영 날짜 추가)
    """
    schedule_data = await common.load_data("/code/app/static/data/meal_schedule.json")
    user_id = _get_user_id(req)
    favorite_places = (
        await cafeteria_favorites.get_favorite_places(user_id) if user_id else set()
    )

    for cafeteria_data in schedule_data:
        place = cafeteria_data.get("place")
        if not cafeteria_data.get("date"):
            operating_date = await common.get_operating_date_for_place(place)
            if operating_date:
                cafeteria_data["date"] = operating_date

    response = cafeteria.create_schedule_response(schedule_data, favorite_places)
    return JSONResponse(response)


@router.post("/menu/today")
async def get_today_menu(req: KakaoRequest):
    """
    req: ex) "기숙사", "제2학생회관", "제3학생회관", "상록회관", "생활과학대학"
    return: 오늘의 메뉴, 요일 퀵리플라이
    """
    utterance = req.userRequest.utterance.strip()
    if _is_favorite_utterance(utterance):
        return await _handle_favorite_fallback(req, utterance)

    place = utterance
    current_kst = common.get_current_kr_time()
    today_weekday = current_kst.weekday()  # 0: 월요일, 1: 화요일, ..., 6: 일요일
    kor_day = common.get_kor_day(today_weekday)

    place_key = common.get_eng_place(place)
    data = await common.load_data(str(common.get_menu_data_path(place_key)))
    menu_data = common.get_menu_by_day(data, kor_day)
    if not menu_data:
        raise HTTPException(status_code=404, detail="해당 요일에 메뉴가 없습니다.")

    response = cafeteria.create_menu_response(kor_day, menu_data, place)
    return JSONResponse(response)


@router.post("/menu/reaction")
async def create_menu_reaction(req: KakaoRequest):
    """
    식단 카드의 반응 버튼 extra를 받아 사용자별 투표를 저장하고 집계 결과를 반환합니다.
    """
    extra = req.action.clientExtra if req.action and req.action.clientExtra else None
    user = req.userRequest.user
    user_id = user.id if user and user.id else None

    if not extra:
        raise HTTPException(status_code=400, detail="반응 정보가 없습니다.")
    if not user_id:
        raise HTTPException(status_code=400, detail="사용자 정보가 없습니다.")

    try:
        result = await menu_reactions.record_reaction(extra, user_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="DB 연결이 준비되지 않았습니다.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response = menu_reactions.create_reaction_response(extra, result)
    return JSONResponse(response)


@router.post("/favorites")
async def get_favorites(req: KakaoRequest):
    user_id = _get_user_id(req)
    if not user_id:
        raise HTTPException(status_code=400, detail="사용자 정보가 없습니다.")

    schedule_data = await common.load_data("/code/app/static/data/meal_schedule.json")
    for cafeteria_data in schedule_data:
        place = cafeteria_data.get("place")
        if not cafeteria_data.get("date"):
            operating_date = await common.get_operating_date_for_place(place)
            if operating_date:
                cafeteria_data["date"] = operating_date

    favorites = await cafeteria_favorites.get_favorite_places(user_id)
    response = await cafeteria_favorites.create_favorites_response(
        schedule_data, favorites
    )
    return JSONResponse(response)


@router.post("/favorites/toggle")
async def update_favorite(req: KakaoRequest):
    user_id = _get_user_id(req)
    if not user_id:
        raise HTTPException(status_code=400, detail="사용자 정보가 없습니다.")

    extra = req.action.clientExtra if req.action and req.action.clientExtra else {}
    utterance = req.userRequest.utterance.strip()
    place = extra.get("place") or cafeteria_favorites.parse_favorite_place(utterance)
    if not place:
        raise HTTPException(status_code=400, detail="식당 정보를 찾을 수 없습니다.")

    enabled = "해제" not in utterance
    result = await cafeteria_favorites.set_favorite(user_id, place, enabled)
    response = cafeteria_favorites.create_toggle_response(result)
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


def _get_user_id(req: KakaoRequest | None) -> str | None:
    if not req or not req.userRequest.user:
        return None
    return req.userRequest.user.id


def _is_favorite_utterance(utterance: str) -> bool:
    return "즐겨찾기" in utterance.replace(" ", "")


async def _handle_favorite_fallback(req: KakaoRequest, utterance: str):
    if cafeteria_favorites.parse_favorite_place(utterance):
        return await update_favorite(req)
    return await get_favorites(req)
