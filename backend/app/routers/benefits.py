from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

from app.schemas.kakao_request import KakaoRequest
from app.services import benefits

router = APIRouter()


def _utterance(req: KakaoRequest | None) -> str:
    return (req.userRequest.utterance if req else "").strip()


@router.post("/home")
async def home(req: KakaoRequest = Body(...)):
    return JSONResponse(benefits.list_response("학교혜택 최신"))


@router.post("/list")
async def list_benefits(req: KakaoRequest = Body(...)):
    return JSONResponse(benefits.list_response(_utterance(req)))


@router.post("/detail")
async def detail(req: KakaoRequest = Body(...)):
    return JSONResponse(benefits.detail_response(_utterance(req)))


@router.post("/page")
async def page(req: KakaoRequest = Body(...)):
    # 고정 messageText 매핑의 첫 버전은 다음 페이지를 최신 목록으로 반환한다.
    return JSONResponse(benefits.list_response("학교혜택 최신", page=1))
