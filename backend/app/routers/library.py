from app.services import library
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/seats")
async def get_nearby_shuttles():
    response = library.create_seats_response()
    return JSONResponse(response)
