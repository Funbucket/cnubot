import logging

from app.schemas.kakao_request import KakaoRequest
from app.services import shuttle, experiments
from app.utils import common
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/nearby")
async def get_nearby_shuttles(req: KakaoRequest = Body(...)):
    data = await common.load_data("/code/app/static/data/shuttle_schedule.json")
    try:
        data["academic_calendar"] = await common.load_data(
            "/code/app/static/data/academic_calendar.json"
        )
    except FileNotFoundError:
        data["academic_calendar"] = {"events": []}
    properties = {"feature": "shuttle"}
    response = shuttle.create_nearby_shuttles_response(data, analytics=properties)
    try:
        await experiments.record_funnel_event(
            req.userRequest.user.id if req.userRequest.user else None,
            "shuttle_view", source="shuttle", properties=properties,
        )
    except Exception:
        logging.getLogger(__name__).warning("Shuttle analytics unavailable")

    return JSONResponse(response)
