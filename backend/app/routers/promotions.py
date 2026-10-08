from app.services import promotions
from app.services import recommendations
from app.services import experiments
from app.services import promotion_settings
from app.schemas.kakao_request import KakaoRequest
import logging
import uuid
import base64
import json
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi import Query

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/toss-shopping")
async def get_toss_shopping_promotion(req: KakaoRequest | None = Body(default=None)):
    # Legacy Kakao mapping now serves the living collection; no shared list is used.
    return await _get_collection_promotion(req, "living")


@router.post("/collections/today-deals")
async def get_today_deals(req: KakaoRequest | None = Body(default=None)):
    user_id = req.userRequest.user.id if req and req.userRequest.user else None
    entry = _promotion_entry_metadata(req)
    request_id = str(uuid.uuid4())
    try:
        await experiments.record_funnel_event(
            user_id, "promotion_entry_click", source=entry["source"],
            properties={"surface": "today_deals", "collection_id": "today_deals",
                        "entry_source": entry["source"], "entry_button_id": entry["button_id"],
                        "entry_button_label": entry["button_label"]}, request_id=request_id,
        )
    except Exception:
        logger.exception("failed to record today deals entry click")
    pairs = await promotions.get_today_deal_products(
        user_id=user_id, limit=6, request_id=request_id, record_exposure=True,
        force_refresh=entry["source"] == "promotion_refresh",
    )
    if not pairs:
        return JSONResponse({"version": "2.0", "template": {"outputs": [
            {"simpleText": {"text": "오늘 특가와 할인 추천 상품을 준비 중이에요. 잠시 후 다시 확인해주세요."}}
        ], "quickReplies": []}})
    click_urls = []
    for position, (product_key, product) in enumerate(pairs, 1):
        if not user_id:
            click_urls.append(None)
            continue
        token = promotions.create_tracking_token(
            user_id, product_key, "today_deals", category_ids=product.get("category_ids"),
            target_url=product.get("url"), taca_item_id=product.get("taca_item_id"),
            surface="today_deals", button_id="today_deals_product", button_label="특가 바로가기",
            position=position, request_id=request_id,
            product_snapshot={"title": product.get("title"), "button_label": "특가 바로가기",
                              "selection_mode": product.get("selection_mode"), "collection_id": "today_deals"},
        )
        click_urls.append(f"{promotions.common.SERVER_URL}/promotions/toss-shopping/click?token={token}")
    return JSONResponse(promotions.create_toss_shopping_list_response(
        [product for _, product in pairs], click_urls, collection_id="today_deals",
    ))


@router.post("/collections/{collection_id}")
async def get_collection_promotion(collection_id: str, req: KakaoRequest | None = Body(default=None)):
    if collection_id not in {"food", "living"}:
        return JSONResponse({"detail": "지원하지 않는 기획전입니다."}, status_code=404)
    return await _get_collection_promotion(req, collection_id)


async def _get_collection_promotion(req: KakaoRequest | None, collection_id: str | None):
    user_id = req.userRequest.user.id if req and req.userRequest.user else None
    entry = _promotion_entry_metadata(req)
    source = entry["source"]
    request_id = str(uuid.uuid4())
    try:
        await experiments.record_funnel_event(
            user_id,
            "promotion_entry_click",
            source=source,
            properties={
                "surface": source,
                "collection_id": collection_id,
                "entry_source": source,
                "entry_button_id": entry["button_id"],
                "entry_button_label": entry["button_label"],
            },
            request_id=request_id,
        )
    except Exception:
        logger.exception("failed to record promotion entry click")
    try:
        product_pairs = await promotions.get_live_toss_products(
            user_id, source, limit=6, request_id=request_id, collection_id=collection_id
        )
    except Exception:
        logger.exception("failed to load live promotion products")
        product_pairs = []
    if not product_pairs and collection_id:
        product_pairs = await promotions.get_collection_fallback_products(
            user_id, source, collection_id, limit=6, request_id=request_id,
        )
    if not product_pairs and (collection_id or promotion_settings.read_settings().mode == "fixed"):
        return JSONResponse({"version": "2.0", "template": {"outputs": [
            {"simpleText": {"text": "상품을 준비 중입니다. 잠시 후 다시 확인해주세요."}}
        ]}})
    if not product_pairs:
        product_pairs = list(promotions.TOSS_SHOPPING_PRODUCTS.items())[:6]
        for product_key, product in product_pairs:
            try:
                await recommendations.record_exposure(
                    user_id,
                    source,
                    int(product["taca_item_id"]) if product.get("taca_item_id") else 0,
                    product.get("category_ids") or [],
                    product_key=product_key,
                    properties={"product_name": product.get("title")},
                    request_id=request_id,
                )
            except Exception:
                logger.exception("failed to record fallback product exposure")
    products = [product for _, product in product_pairs]
    click_urls = []
    for position, (product_key, product) in enumerate(product_pairs, 1):
        if not user_id:
            click_urls.append(None)
            continue
        token = promotions.create_tracking_token(
            user_id, product_key, source,
            category_ids=product.get("category_ids"), target_url=product.get("url"),
            taca_item_id=product.get("taca_item_id"), surface="commerce_card",
            button_id=entry["button_id"], button_label=entry["button_label"],
            position=position, request_id=request_id,
            product_snapshot={key: product.get(key) for key in
                              ("title", "button_label", "settings_revision", "selection_mode", "collection_id")},
        )
        click_urls.append(f"{promotions.common.SERVER_URL}/promotions/toss-shopping/click?token={token}")
    return JSONResponse(promotions.create_toss_shopping_list_response(products, click_urls, collection_id))


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
        if value in {"menu_button", "quick_reply", "menu_inline_more", "promotion_refresh"}:
            return {
                "source": value,
                "button_id": payload.get("button_id") or "unknown",
                "button_label": payload.get("button_label") or "unknown",
            }
    return unknown


@router.get("/toss-shopping/click")
async def track_toss_shopping_click(token: str = Query(..., min_length=20), request: Request = None):
    decoded = promotions.read_tracking_token(token)
    if not decoded:
        return JSONResponse({"detail": "유효하지 않거나 만료된 링크입니다."}, status_code=400)
    user_id, product_key, _source, category_ids, target_url, taca_item_id, surface, button_id, button_label, position, request_id = decoded
    # Read metadata only after signature and expiry validation above.
    payload = token.split(".", 1)[0]
    snapshot = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("m", {})
    agent = request.headers.get("user-agent", "").lower() if request else ''
    is_bot = any(word in agent for word in ('bot','crawler','spider','facebookexternalhit','slackbot','preview'))
    try:
        if not snapshot.get("is_preview") and not is_bot:
            await recommendations.record_category_click(
                user_id, category_ids, taca_item_id, surface, request_id
            )
    except Exception:
        logger.exception("failed to record recommendation click")
    try:
        product = promotions.get_product(product_key)
        properties = {
                "surface": surface,
                "is_preview": bool(snapshot.get("is_preview")),
                "preview_session_id": snapshot.get("preview_session_id"),
                "source_experiment_id": snapshot.get("experiment_id"),
                "source_variant": snapshot.get("planned_variant"),
                "bundle_id": snapshot.get("bundle_id"),
                "config_hash": snapshot.get("config_hash"),
                "collection_id": snapshot.get("collection_id"),
                "entry_source": _source,
                "entry_button_id": button_id,
                "entry_button_label": button_label,
                "product_name": snapshot.get("title") or product.get("title"),
                "category_name": ", ".join(product.get("category_names") or []),
                "candidate_sources": product.get("candidate_sources") or [],
                "selection_mode": snapshot.get("selection_mode") or ("fixed" if product_key.startswith("fixed_") else "algorithm"),
                "product_button_label": snapshot.get("button_label") or product.get("button_label"),
                "settings_revision": snapshot.get("settings_revision"),
                "position": position,
                "card_position": position,
                "row": (position - 1) // promotions.COMMERCE_CARDS_PER_ROW + 1 if position else None,
                "column": (position - 1) % promotions.COMMERCE_CARDS_PER_ROW + 1 if position else None,
            }
        properties['click_filter_version'] = 'signed-external-v1'
        properties['filter_reason'] = 'known_preview_agent' if is_bot else None
        await experiments.record_funnel_event(
            user_id, 'commerce_card_click_raw', source=_source, product_key=product_key,
            taca_item_id=taca_item_id, properties=properties, request_id=request_id)
        if not is_bot:
            await experiments.record_funnel_event(
                user_id, 'commerce_card_click', source=_source, product_key=product_key,
                taca_item_id=taca_item_id, properties=properties, request_id=request_id)
    except Exception:
        logger.exception("failed to record commerce card click")
    # 302 is handled more consistently than 307 by Kakao's in-app browser
    # when redirecting from our tracking endpoint to an external Toss URL.
    return RedirectResponse(target_url or promotions.get_product(product_key)["url"], status_code=302)
