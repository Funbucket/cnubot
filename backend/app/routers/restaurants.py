import asyncio

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from app.schemas.kakao_request import KakaoRequest
from app.services import restaurant_catalog, restaurants

router = APIRouter()


async def respond(kind: str, req: KakaoRequest):
    utterance = req.userRequest.utterance.strip()
    if utterance not in restaurants.ROUTE_MESSAGES[kind]:
        return JSONResponse(restaurants.home_response("지역부터 골라주세요."))
    user_id = req.userRequest.user.id if req.userRequest.user else None
    return JSONResponse(await restaurants.browse_response(utterance, user_id))


@router.post("/home")
async def home(req: KakaoRequest = Body(...)):
    return await respond("home", req)


@router.post("/random")
async def random(req: KakaoRequest = Body(...)):
    return await respond("random", req)


@router.post("/area")
async def area(req: KakaoRequest = Body(...)):
    return await respond("area", req)


@router.post("/budget")
async def budget(req: KakaoRequest = Body(...)):
    return await respond("budget", req)


@router.post("/rating")
async def rating(req: KakaoRequest = Body(...)):
    return await respond("rating", req)


@router.post("/more")
async def more(req: KakaoRequest = Body(...)):
    return await respond("more", req)


@router.get("/map")
async def map_redirect(token: str = Query(..., max_length=3000)):
    now = restaurant_catalog.now_kst()
    payload = restaurants.read_map_token(token, now)
    if not payload:
        raise HTTPException(status_code=400, detail="링크가 만료되었거나 올바르지 않습니다.")
    catalog = await asyncio.to_thread(restaurant_catalog.safe_catalog)
    item = next((item for item in catalog.items if item.id == payload["place_id"] and item.enabled), None)
    if not item:
        raise HTTPException(status_code=404, detail="현재 안내 중인 식당이 아닙니다.")
    try:
        from app.database import get_pool
        async with get_pool().acquire() as conn:
            await restaurants.record_event(conn, "map_click", payload["user_hash"], payload["session_id"],
                {key: payload.get(key) for key in ("place_id", "area", "budget", "min_rating", "mode", "exposed_at")},
                event_id="click:" + payload["click_id"])
    except Exception:
        restaurants.logger.warning("Restaurant map analytics unavailable")
    return RedirectResponse(item.place_url, status_code=302,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
