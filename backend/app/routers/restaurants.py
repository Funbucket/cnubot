from app.schemas.kakao_request import KakaoRequest
from app.services import restaurants
from fastapi import APIRouter, Body
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/nearby")
async def get_nearby_restaurants(req: KakaoRequest | None = Body(default=None)):
    utterance = req.userRequest.utterance.strip() if req else ""
    area = restaurants.parse_area(utterance)

    try:
        response = await run_in_threadpool(
            restaurants.get_nearby_restaurants_response, area
        )
    except restaurants.KakaoLocalConfigError:
        response = restaurants.create_kakao_config_required_response()
    except restaurants.KakaoLocalApiError:
        response = restaurants.create_kakao_api_unavailable_response()

    return JSONResponse(response)
