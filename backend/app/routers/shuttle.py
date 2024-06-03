import os

from app.services import shuttle
from app.utils import common
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse

router = APIRouter()


@router.post("/nearby")
async def get_nearby_shuttles():
    data = await common.load_data("/app/static/data/shuttle_schedule.json")
    response = shuttle.create_nearby_shuttles_response(data)

    return JSONResponse(response)


@router.get("/images/{image_name}")
async def get_image(image_name: str):
    """
    image_name: 이미지 파일 이름 (예: a_routes.jpg)
    return: 이미지 파일
    """
    file_path = f"app/static/images/{image_name}"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")
