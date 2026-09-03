from app.services import promotions
from app.services import experiments
from app.schemas.kakao_request import KakaoRequest
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

router = APIRouter()


@router.post("/toss-shopping")
async def get_toss_shopping_promotion(req: KakaoRequest | None = Body(default=None)):
    user_id = req.userRequest.user.id if req and req.userRequest.user else None
    await experiments.record_event(
        promotions.PROMOTION_EXPERIMENT_KEY,
        user_id,
        "promotion_click",
        {"surface": "promotion_block"},
    )
    variant = await experiments.get_active_variant(promotions.PROMOTION_EXPERIMENT_KEY, user_id)
    product_key = (variant or {}).get("config", {}).get("product_key")
    return JSONResponse(promotions.create_toss_shopping_response(promotions.get_product(product_key)))
