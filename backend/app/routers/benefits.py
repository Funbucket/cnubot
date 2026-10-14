from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.schemas.kakao_request import KakaoRequest
from app.services import benefits

router = APIRouter()


def _utterance(req: KakaoRequest | None) -> str:
    return (req.userRequest.utterance if req else "").strip()


def _user_id(req: KakaoRequest) -> str | None:
    return req.userRequest.user.id if req.userRequest.user else None


@router.post("/home")
async def home(req: KakaoRequest = Body(...)):
    return JSONResponse(await benefits.browse_response("학교혜택 최신", _user_id(req), show_intro=True))


@router.post("/list")
async def list_benefits(req: KakaoRequest = Body(...)):
    return JSONResponse(await benefits.browse_response(_utterance(req), _user_id(req)))


@router.post("/detail")
async def detail(req: KakaoRequest = Body(...)):
    return JSONResponse(benefits.detail_response(_utterance(req)))


@router.post("/page")
async def page(req: KakaoRequest = Body(...)):
    return JSONResponse(await benefits.browse_response(_utterance(req), _user_id(req)))
