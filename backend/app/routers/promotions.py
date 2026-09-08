from app.services import promotions
from app.services import recommendations
from app.schemas.kakao_request import KakaoRequest
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import Query

router = APIRouter()


@router.post("/toss-shopping")
async def get_toss_shopping_promotion(req: KakaoRequest | None = Body(default=None)):
    user_id = req.userRequest.user.id if req and req.userRequest.user else None
    try:
        product_key, product = await promotions.get_live_toss_product(user_id, "quick_reply")
    except Exception:
        product_key = promotions.DEFAULT_PROMOTION_PRODUCT_KEY
    product = promotions.get_product(product_key)
    click_url = (
        f"{promotions.common.SERVER_URL}/promotions/toss-shopping/click?token="
        f"{promotions.create_tracking_token(user_id, product_key, 'commerce_card', product.get('category_ids'), product.get('url'), product.get('taca_item_id'), 'quick_reply')}"
        if user_id and product_key
        else None
    )
    return JSONResponse(promotions.create_toss_shopping_response(product, click_url))


@router.get("/toss-shopping/click")
async def track_toss_shopping_click(token: str = Query(..., min_length=20)):
    decoded = promotions.read_tracking_token(token)
    if not decoded:
        return JSONResponse({"detail": "유효하지 않거나 만료된 링크입니다."}, status_code=400)
    user_id, product_key, _source, category_ids, target_url, taca_item_id, surface = decoded
    await recommendations.record_category_click(user_id, category_ids, taca_item_id, surface)
    # 302 is handled more consistently than 307 by Kakao's in-app browser
    # when redirecting from our tracking endpoint to an external Toss URL.
    return RedirectResponse(target_url or promotions.get_product(product_key)["url"], status_code=302)
