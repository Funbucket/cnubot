from app.services import promotions
from app.services import recommendations
from app.services import experiments
from app.schemas.kakao_request import KakaoRequest
from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import Query

router = APIRouter()


@router.post("/toss-shopping")
async def get_toss_shopping_promotion(req: KakaoRequest | None = Body(default=None)):
    user_id = req.userRequest.user.id if req and req.userRequest.user else None
    entry = _promotion_entry_metadata(req)
    source = entry["source"]
    try:
        await experiments.record_funnel_event(
            user_id,
            "promotion_entry_click",
            source=source,
            properties={
                "surface": source,
                "entry_source": source,
                "entry_button_id": entry["button_id"],
                "entry_button_label": entry["button_label"],
            },
        )
    except Exception:
        pass
    try:
        product_pairs = await promotions.get_live_toss_products(user_id, source, limit=6)
    except Exception:
        product_pairs = []
    if not product_pairs:
        product_pairs = list(promotions.TOSS_SHOPPING_PRODUCTS.items())[:6]
    products = [product for _, product in product_pairs]
    for product_key, product in product_pairs:
        try:
            await experiments.record_funnel_event(
                user_id,
                "promotion_exposure",
                source=source,
                product_key=product_key,
                taca_item_id=product.get("taca_item_id"),
                properties={
                    "surface": "commerce_card",
                    "entry_source": source,
                    "entry_button_id": entry["button_id"],
                    "entry_button_label": entry["button_label"],
                    "product_name": product.get("title"),
                    "category_name": ", ".join(product.get("category_names") or []),
                    "candidate_sources": product.get("candidate_sources") or [],
                },
            )
        except Exception:
            pass
    click_urls = [
        (
            f"{promotions.common.SERVER_URL}/promotions/toss-shopping/click?token="
            f"{promotions.create_tracking_token(user_id, product_key, source, product.get('category_ids'), product.get('url'), product.get('taca_item_id'), 'commerce_card', entry['button_id'], entry['button_label'])}"
            if user_id
            else None
        )
        for product_key, product in product_pairs
    ]
    return JSONResponse(promotions.create_toss_shopping_list_response(products, click_urls))


def _promotion_entry_metadata(req: KakaoRequest | None) -> dict[str, str]:
    unknown = {
        "source": "unknown",
        "button_id": "unknown",
        "button_label": "unknown",
    }
    if not req or not req.action:
        return unknown
    for payload in (req.action.clientExtra, req.action.extra):
        payload = payload or {}
        value = payload.get("source")
        if value in {"menu_button", "quick_reply"}:
            return {
                "source": value,
                "button_id": payload.get("button_id") or "unknown",
                "button_label": payload.get("button_label") or "unknown",
            }
    return unknown


@router.get("/toss-shopping/click")
async def track_toss_shopping_click(token: str = Query(..., min_length=20)):
    decoded = promotions.read_tracking_token(token)
    if not decoded:
        return JSONResponse({"detail": "유효하지 않거나 만료된 링크입니다."}, status_code=400)
    user_id, product_key, _source, category_ids, target_url, taca_item_id, surface, button_id, button_label = decoded
    await recommendations.record_category_click(user_id, category_ids, taca_item_id, surface)
    try:
        product = promotions.get_product(product_key)
        await experiments.record_funnel_event(
            user_id,
            "commerce_card_click",
            source=_source,
            product_key=product_key,
            taca_item_id=taca_item_id,
            properties={
                "surface": surface,
                "entry_source": _source,
                "entry_button_id": button_id,
                "entry_button_label": button_label,
                "product_name": product.get("title"),
                "category_name": ", ".join(product.get("category_names") or []),
                "candidate_sources": product.get("candidate_sources") or [],
            },
        )
    except Exception:
        pass
    # 302 is handled more consistently than 307 by Kakao's in-app browser
    # when redirecting from our tracking endpoint to an external Toss URL.
    return RedirectResponse(target_url or promotions.get_product(product_key)["url"], status_code=302)
