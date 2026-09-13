from app.services import shuttle
from app.utils import common
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/nearby")
async def get_nearby_shuttles():
    data = await common.load_data("/code/app/static/data/shuttle_schedule.json")
    try:
        data["academic_calendar"] = await common.load_data(
            "/code/app/static/data/academic_calendar.json"
        )
    except FileNotFoundError:
        data["academic_calendar"] = {"events": []}
    response = shuttle.create_nearby_shuttles_response(data)

    return JSONResponse(response)
