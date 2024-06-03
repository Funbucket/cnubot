from app.services import help
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/contact")
async def contact_help_center():
    response = help.create_help_center_response()
    return JSONResponse(response)
