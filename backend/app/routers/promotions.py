from app.services import promotions
from app.services import experiments
from app.schemas.kakao_request import KakaoRequest
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import Query

router = APIRouter()


@router.post("/toss-shopping")
async def get_toss_shopping_promotion(req: KakaoRequest | None = Body(default=None)):
    user_id = req.userRequest.user.id if req and req.userRequest.user else None
    source = "promotion_block"
    if req and req.action and req.action.clientExtra:
        source = req.action.clientExtra.get("source", source)
    event_name = {
        "menu_button": "promotion_button_click",
        "quick_reply": "promotion_quick_reply_click",
    }.get(source, "promotion_block_click")
    await experiments.record_event(
        promotions.PROMOTION_EXPERIMENT_KEY,
        user_id,
        event_name,
        {"surface": source},
    )
    variant = await experiments.get_active_variant(promotions.PROMOTION_EXPERIMENT_KEY, user_id)
    product_key = (variant or {}).get("config", {}).get("product_key")
    return JSONResponse(promotions.create_toss_shopping_response(promotions.get_product(product_key)))


@router.get("/toss-shopping/click")
async def track_toss_shopping_click(token: str = Query(..., min_length=20)):
    decoded = promotions.read_tracking_token(token)
    if not decoded:
        return JSONResponse({"detail": "유효하지 않거나 만료된 링크입니다."}, status_code=400)
    user_id, product_key = decoded
    await experiments.record_event(
        promotions.PROMOTION_EXPERIMENT_KEY,
        user_id,
        "promotion_button_click",
        {"surface": "tracked_web_link", "product_key": product_key},
    )
    return RedirectResponse(promotions.get_product(product_key)["url"], status_code=307)
