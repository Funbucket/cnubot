from app.services import promotions
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/toss-shopping")
async def get_toss_shopping_promotion():
    return JSONResponse(promotions.create_toss_shopping_response())
