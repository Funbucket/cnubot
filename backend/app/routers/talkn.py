from app.services import talkn
from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("")
async def get_talkn():
    return JSONResponse(talkn.create_talkn_response())
