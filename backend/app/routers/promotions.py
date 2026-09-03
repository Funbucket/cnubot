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
    product = promotions.get_product(product_key)
    click_url = (
        f"{promotions.common.SERVER_URL}/promotions/toss-shopping/click?token="
        f"{promotions.create_tracking_token(user_id, product_key, 'commerce_card')}"
        if user_id and product_key
        else None
    )
    return JSONResponse(promotions.create_toss_shopping_response(product, click_url))


@router.get("/toss-shopping/click")
async def track_toss_shopping_click(token: str = Query(..., min_length=20)):
    decoded = promotions.read_tracking_token(token)
    if not decoded:
        return JSONResponse({"detail": "유효하지 않거나 만료된 링크입니다."}, status_code=400)
    user_id, product_key, source = decoded
    event_name = {
        "commerce_card": "commerce_card_click",
        "promotion_button": "promotion_button_click",
    }.get(source, "promotion_button_click")
    await experiments.record_event(
        promotions.PROMOTION_EXPERIMENT_KEY,
        user_id,
        event_name,
        {"surface": "tracked_web_link", "product_key": product_key, "source": source},
    )
    # 302 is handled more consistently than 307 by Kakao's in-app browser
    # when redirecting from our tracking endpoint to an external Toss URL.
    return RedirectResponse(promotions.get_product(product_key)["url"], status_code=302)
