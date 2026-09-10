import base64
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils import common, kakao_json_response
from app.services import toss_sharelink
from app.services import recommendations
from app.services import promotion_settings

PROMOTION_EXPERIMENT_KEY = "snack_product_comparison_v3"
DEFAULT_PROMOTION_PRODUCT_KEY = "pepsi_lime"
TOSS_MENU_BUTTON_LABEL = "🛍️ 토스 제휴 특가"
TOSS_DORM_MENU_BUTTON_LABEL = "🏠 기숙사생 특가"
TOSS_LIVING_MENU_BUTTON_LABEL = "🛍️ 기숙사·자취생 특가"
QUICK_REPLY_LABELS = (
    "🔥최대93%할인",
    "🎓대학생최대93%",
    "🏠기숙사생특가",
    "🛍️자취생추천특가",
    "💸9900원부터특가",
    "⚡오늘의TOP3특가",
    "🎁학생인기상품",
    "🚚무료배송특가",
    "💰1만원이하추천",
    "⏰오늘만이가격",
    "🔥오늘의초특가",
    "👑역대급특가",
)
MENU_BUTTON_LABELS = (
    "🔥93%초특가",
    "🎓대학생특가",
    "🏠기숙사특가",
    "🛍️자취생특가",
    "💸9900원부터",
    "⚡오늘의TOP3",
    "🎁인기상품",
    "🚚무료배송",
    "💰1만원이하",
    "⏰오늘만이가격",
    "🔥오늘의초특가",
    "👑역대급특가",
)
TOSS_CANDIDATE_POOL_SIZE = 100
COMMERCE_CARDS_PER_ROW = 3
KST = ZoneInfo("Asia/Seoul")

# 학식 응답에 상품을 바로 끼워넣는 카드는 진입 버튼과 달리 무시 비용이 크므로,
# 아래 기준을 통과하는 상품이 없으면 카드를 아예 노출하지 않는다.
INLINE_CARD_SURFACE = "menu_inline_card"
INLINE_CARD_MAX_PRICE = 20000
INLINE_CARD_MIN_DISCOUNT_RATE = 30
# commerceCard는 title 30자, description 40자까지 노출한다.
INLINE_CARD_BUTTON_LIMIT = 14
COMMERCE_CARD_TITLE_LIMIT = 30
COMMERCE_CARD_DESCRIPTION_LIMIT = 40
# 대용량·가정용 수량은 자취생과 맞지 않아 인라인 노출에서 제외한다.
_BULK_QUANTITY_LIMITS = (
    ("개입", 100), ("개", 100), ("매", 300), ("롤", 12),
    ("팩", 5), ("박스", 1), ("포", 60), ("봉", 5), ("kg", 2),
)
_BULK_QUANTITY_PATTERN = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(개입|개|매|롤|팩|박스|포|봉|kg|KG)"
)


def _rotating_label(labels: tuple[str, ...]) -> str:
    """Keep one label stable for a 2-hour KST slot, then rotate sequentially."""
    now = datetime.now(KST)
    slot_number = now.date().toordinal() * 12 + now.hour // 2
    return labels[slot_number % len(labels)]

TOSS_SHOPPING_PRODUCTS = {
    "yellow_cheese_buttering": {
        "title": "해태 버터링 딥황치즈맛 4개",
    "button_label": "🍪 황치즈 버터링 특가 · 제휴",
    "quick_reply_label": "🍪 황치즈 버터링 특가 · 제휴",
    "description": "🍪 황치즈 덕후 주목! 첫 구매 3,000원 추가 할인",
    "original_price": 19200,
    "price": 14500,
    "discount": 4700,
    "discount_rate": 24,
    "url": "https://toss.im/_m/FLJEEeY4",
    "image_url": (
        "https://resources-fe.toss.im/image-optimize/width=2400,quality=90/"
        "https%3A%2F%2Fshopping.toss.im%2Flive%2Ftemp%2F2026-08-26%2F"
        "e51d1317-1639-4907-9f86-5f45118c732f.png"
    ),
    },
    "lactofit_gold": {
        "title": "락토핏 골드 140포 2개 + 증정",
        "button_label": "💊 유산균 특가 · 제휴",
        "quick_reply_label": "💊 유산균 특가 · 제휴",
        "description": "💊 매일 챙기는 유산균, 무료배송 특가로 만나보세요",
        "original_price": 148400,
        "price": 51987,
        "discount": 96413,
        "discount_rate": 64,
        "url": "https://toss.im/_m/XddZXers",
        "image_url": "https://resources-fe.toss.im/image-optimize/width=2400,quality=90/https%3A%2F%2Fshopping.toss.im%2Flive%2Ftemp%2F2026-08-03%2F74828108-78eb-4328-bf27-62b32a559495.jpeg",
    },
    "lavender_wipes": {
        "title": "리벤스 라벤더 바이올렛 물티슈",
        "button_label": "🧻 물티슈 특가 · 제휴",
        "quick_reply_label": "🧻 물티슈 특가 · 제휴",
        "description": "🧻 1매당 8원 · 무료배송 특가",
        "original_price": 29900,
        "price": 7500,
        "discount": 22400,
        "discount_rate": 74,
        "url": "https://toss.im/_m/1LO7hURq",
        "image_url": "https://resources-fe.toss.im/image-optimize/width=800,quality=75/https%3A%2F%2Fshopping.toss.im%2Flive%2Ftemp%2F2026-01-08%2F15629a7e-56c2-4f73-8896-6481eaffdbca.jpeg",
    },
    "cento_toothbrush": {
        "title": "센토 프라임 바이브 칫솔 20개입",
        "button_label": "🪥 칫솔 특가 · 제휴",
        "quick_reply_label": "🪥 칫솔 특가 · 제휴",
        "description": "🪥 초미세 탄력모 칫솔 20개입 특가",
        "original_price": 26500,
        "price": 15900,
        "discount": 10600,
        "discount_rate": 40,
        "url": "https://toss.im/_m/rZBiP883",
        "image_url": "https://resources-fe.toss.im/image-optimize/width=800,quality=75/https%3A%2F%2Fshopping.toss.im%2Flive%2Ftaca%2Fai%2Fv2%2FNzE0ZWM1%2FQU9PYmQ1N3pyMWY2SE8vaFZPcVZ2d0gxRk9nQjdGVHFrVlVZRUM4VmVuLzg.png",
    },
    "pepsi_lime": {
        "title": "펩시 제로슈거 라임 245ml 30개",
        "button_label": "🥤 펩시 라임 특가 · 제휴",
        "quick_reply_label": "🥤 펩시 라임 특가 · 제휴",
        "description": "🥤 상쾌한 라임향 제로 탄산, 20% 할인",
        "original_price": 17900,
        "price": 14200,
        "discount": 3700,
        "discount_rate": 20,
        "url": "https://toss.im/_m/zeU1Q3n2",
        "image_url": "https://resources-fe.toss.im/image-optimize/width=2400,quality=90/https%3A%2F%2Fshopping.toss.im%2Flive%2Ftaca%2Fai%2FYTI5M2Zm%2FQU9LVVlwd3p2NzlCdld1TVk5enZudUZXcTFFcnN4Q3JuS3ZVUUw2dlZKOWg.png",
    },
    "softener_soap": {
        "title": "수뜰리에 섬유유연제 비누향 2.5L 4개",
        "button_label": "🧺 섬유유연제 특가 · 제휴",
        "quick_reply_label": "🧺 섬유유연제 특가 · 제휴",
        "description": "🧺 비누향 섬유유연제 88% 할인",
        "original_price": 39600,
        "price": 4590,
        "discount": 35010,
        "discount_rate": 88,
        "url": "https://toss.im/_m/lXf00Eti",
        "image_url": "https://resources-fe.toss.im/image-optimize/width=2400,quality=90/https%3A%2F%2Fshopping.toss.im%2Flive%2Ftemp%2F2026-08-10%2F1e4fe51d-5eff-40b9-82e5-057e3a8529d9.png",
    },
}

TOSS_SHOPPING_PROMOTION = TOSS_SHOPPING_PRODUCTS[DEFAULT_PROMOTION_PRODUCT_KEY]

_PROMOTION_LABELS = (
    (("펩시", "라임"), "🥤 펩시 라임 특가"),
    (("버터링",), "🍪 버터링 특가"),
    (("락토핏",), "💊 락토핏 특가"),
    (("물티슈",), "🧻 물티슈 특가"),
    (("칫솔",), "🪥 칫솔 특가"),
    (("섬유유연제",), "🧺 섬유유연제 특가"),
    (("삼겹살",), "🥩 삼겹살 특가"),
)

_CATEGORY_EMOJIS = (
    (("음료", "커피", "차"), "🥤"),
    (("식품", "간식", "과자", "축산", "수산", "농산"), "🍽️"),
    (("패션", "의류", "신발", "가방", "잡화"), "👕"),
    (("화장품", "미용", "뷰티"), "💄"),
    (("가구", "홈데코", "인테리어"), "🛋️"),
    (("가전", "디지털", "컴퓨터", "전자"), "🔌"),
    (("생활", "주방", "욕실", "청소"), "🧺"),
    (("반려", "애완"), "🐾"),
    (("유아", "아동", "출산", "완구"), "🧸"),
    (("스포츠", "레저", "골프", "캠핑"), "⚽"),
    (("자동차", "공구", "산업"), "🔧"),
    (("도서", "문구", "오피스"), "📚"),
    (("여행", "티켓", "공연", "문화"), "🎫"),
)


def promotion_label(title: str, category_names: list[str] | None = None) -> str:
    for keywords, label in _PROMOTION_LABELS:
        if all(keyword in title for keyword in keywords):
            return f"{label} · 제휴"
    category_text = " ".join(category_names or [])
    emoji = "🛍️"
    for keywords, candidate_emoji in _CATEGORY_EMOJIS:
        if any(keyword in category_text for keyword in keywords):
            emoji = candidate_emoji
            break
    compact_title = title.split(",", 1)[0].split("(", 1)[0].strip()
    compact_title = compact_title[:8].strip() or "추천 상품"
    return f"{emoji} {compact_title} 특가 · 제휴"[:20]


async def _annotate_candidate_categories(candidates: list[dict]) -> list[dict]:
    try:
        category_tree = await toss_sharelink.categories()
    except Exception:
        return candidates
    annotated = []
    for candidate in candidates:
        item = dict(candidate)
        item["_category_names"] = [
            name
            for category_id in item.get("categoryIds", [])
            for name in category_tree.get(int(category_id), [])
        ]
        annotated.append(item)
    return annotated


async def _candidate_pool() -> list[dict]:
    """Merge cached Toss sources into one deduplicated recommendation pool."""
    try:
        category_tree = await toss_sharelink.categories()
    except Exception:
        category_tree = {}

    category_ids: list[int] = []
    category_keywords = ("식품", "생활", "주방", "가전", "문구", "뷰티")
    for keyword in category_keywords:
        matches = [
            (category_id, path)
            for category_id, path in category_tree.items()
            if any(keyword in name for name in path)
        ]
        # Prefer a deeper category so its best ranking is more specific.
        matches.sort(key=lambda pair: len(pair[1]), reverse=True)
        if matches:
            category_ids.append(matches[0][0])

    async def safe_call(factory, *args):
        try:
            return await factory(*args)
        except Exception:
            return []

    requests = [
        safe_call(toss_sharelink.best_selling, TOSS_CANDIDATE_POOL_SIZE),
        safe_call(toss_sharelink.today_deals, 30),
    ]
    requests.extend(safe_call(toss_sharelink.best_categories, category_id, 20) for category_id in category_ids)
    results = await asyncio.gather(*requests)
    merged: dict[int, dict] = {}
    for index, items in enumerate(results):
        source = "best_selling" if index == 0 else "today_deals" if index == 1 else "category_best"
        for rank, item in enumerate(items, 1):
            try:
                item_id = int(item["tacaItemId"])
            except (KeyError, TypeError, ValueError):
                continue
            if item_id not in merged:
                candidate = dict(item)
                candidate["_candidate_sources"] = []
                candidate["_source_ranks"] = {}
                merged[item_id] = candidate
            candidate = merged[item_id]
            if source not in candidate["_candidate_sources"]:
                candidate["_candidate_sources"].append(source)
            candidate["_source_ranks"][source] = min(
                rank, candidate["_source_ranks"].get(source, rank)
            )
            if source == "today_deals" and item.get("endAt"):
                candidate["_deal_end_at"] = item["endAt"]
    return await _annotate_candidate_categories(list(merged.values()))


async def get_live_toss_product(
    user_id: str | None = None,
    surface: str = "default",
    preferred_item_id: int | None = None,
    request_id: str | None = None,
    record_exposure: bool = True,
) -> tuple[str, dict]:
    candidates = await _candidate_pool()
    affinity = await recommendations.category_affinity(user_id)
    recent_ids = await recommendations.recent_item_ids(user_id)
    item = next(
        (candidate for candidate in candidates
         if preferred_item_id and int(candidate.get("tacaItemId", 0)) == preferred_item_id),
        None,
    )
    if item is None:
        item = recommendations.rank_candidates(candidates, affinity, recent_ids, user_id, surface)
    if not item:
        raise toss_sharelink.TossSharelinkError("NO_AVAILABLE_TOSS_PRODUCT")
    item_id = int(item["tacaItemId"])
    detail = await toss_sharelink.detail(item_id)
    link = await toss_sharelink.issue_link(item_id)
    source = detail or item
    category_ids = source.get("categoryIds") or item.get("categoryIds", [])
    try:
        category_tree = await toss_sharelink.categories()
    except toss_sharelink.TossSharelinkError:
        category_tree = {}
    category_names = [
        category_tree.get(int(category_id), [""])[-1]
        for category_id in category_ids
        if category_tree.get(int(category_id))
    ]
    product_key = f"toss_item_{item_id}"
    TOSS_SHOPPING_PRODUCTS[product_key] = {
        "title": source.get("displayName") or item.get("displayName", "토스쇼핑 상품"),
        "button_label": promotion_label(source.get("displayName") or item.get("displayName", ""), category_names),
        "quick_reply_label": promotion_label(source.get("displayName") or item.get("displayName", ""), category_names),
        "description": "토스쇼핑 인기 상품",
        "original_price": source.get("originalPrice") or item.get("originalPrice", 0),
        "price": source.get("displayPrice") or item.get("displayPrice", 0),
        "discount": max((source.get("originalPrice") or 0) - (source.get("displayPrice") or 0), 0),
        "discount_rate": source.get("discountRate") or item.get("discountRate", 0),
        "url": link,
        "image_url": source.get("thumbnailUrl") or item.get("thumbnailUrl", ""),
        "taca_item_id": item_id,
        "category_ids": category_ids,
        "category_names": category_names,
        "candidate_sources": item.get("_candidate_sources", []),
    }
    if record_exposure:
        await recommendations.record_exposure(
            user_id,
            surface,
            item_id,
            TOSS_SHOPPING_PRODUCTS[product_key]["category_ids"],
            product_key=product_key,
            properties={"product_name": TOSS_SHOPPING_PRODUCTS[product_key]["title"]},
            request_id=request_id,
        )
    return product_key, TOSS_SHOPPING_PRODUCTS[product_key]


async def get_live_toss_products(
    user_id: str | None = None,
    surface: str = "quick_reply",
    limit: int = 5,
    request_id: str | None = None,
) -> list[tuple[str, dict]]:
    settings = promotion_settings.read_settings()
    if settings.mode == "fixed":
        try:
            products = (await asyncio.wait_for(promotion_settings.resolved_fixed_products(settings), timeout=3.5))[:limit]
        except asyncio.TimeoutError:
            products = promotion_settings.fixed_products(settings)[:limit]
        for position, (key, product) in enumerate(products, 1):
            TOSS_SHOPPING_PRODUCTS[key] = product
            try:
                await recommendations.record_exposure(
                    user_id, surface, product.get("taca_item_id") or 0, product.get("category_ids") or [], product_key=key,
                    properties={"product_name": product["title"], "position": position,
                                "row": (position - 1) // 3 + 1, "column": (position - 1) % 3 + 1,
                                "selection_mode": "fixed", "settings_revision": settings.revision,
                                "product_button_label": product["button_label"]},
                    request_id=request_id,
                )
            except Exception:
                # Analytics failure must never replace the administrator's selection.
                logging.getLogger(__name__).exception("failed to record fixed product exposure")
        return products
    candidates = await _candidate_pool()
    affinity = await recommendations.category_affinity(user_id)
    recent_ids = await recommendations.recent_item_ids(user_id)
    ranked_items = recommendations.rank_candidates_ordered(
        candidates, affinity, recent_ids, user_id, surface, limit
    )
    products: list[tuple[str, dict]] = []
    for item in ranked_items:
        try:
            item_id = int(item["tacaItemId"])
            detail = await toss_sharelink.detail(item_id)
            link = await toss_sharelink.issue_link(item_id)
            source = detail or item
            category_ids = source.get("categoryIds") or item.get("categoryIds", [])
            try:
                category_tree = await toss_sharelink.categories()
            except toss_sharelink.TossSharelinkError:
                category_tree = {}
            category_names = [
                category_tree.get(int(category_id), [""])[-1]
                for category_id in category_ids
                if category_tree.get(int(category_id))
            ]
            product_key = f"toss_item_{item_id}"
            TOSS_SHOPPING_PRODUCTS[product_key] = {
                "title": source.get("displayName") or item.get("displayName", "토스쇼핑 상품"),
                "button_label": promotion_label(source.get("displayName") or item.get("displayName", ""), category_names),
                "quick_reply_label": promotion_label(source.get("displayName") or item.get("displayName", ""), category_names),
                "description": "토스쇼핑 인기 상품",
                "original_price": source.get("originalPrice") or item.get("originalPrice", 0),
                "price": source.get("displayPrice") or item.get("displayPrice", 0),
                "discount": max((source.get("originalPrice") or 0) - (source.get("displayPrice") or 0), 0),
                "discount_rate": source.get("discountRate") or item.get("discountRate", 0),
                "url": link,
                "image_url": source.get("thumbnailUrl") or item.get("thumbnailUrl", ""),
                "taca_item_id": item_id,
                "category_ids": category_ids,
                "category_names": category_names,
                "candidate_sources": item.get("_candidate_sources", []),
            }
            product = TOSS_SHOPPING_PRODUCTS[product_key]
            await recommendations.record_exposure(
                user_id,
                surface,
                item_id,
                category_ids,
                product_key=product_key,
                properties={
                    "product_name": product["title"],
                    "position": len(products) + 1,
                    "row": len(products) // 3 + 1,
                    "column": len(products) % 3 + 1,
                },
                request_id=request_id,
            )
            products.append((product_key, product))
        except (KeyError, TypeError, ValueError, toss_sharelink.TossSharelinkError):
            continue
    return products


def _tracking_secret() -> bytes:
    secret = os.getenv("PROMOTION_TRACKING_SECRET", "").strip()
    if not secret:
        raise RuntimeError("PROMOTION_TRACKING_SECRET is not set")
    return secret.encode()

def create_tracking_token(
    user_id: str,
    product_key: str,
    source: str = "promotion_button",
    category_ids: list[int] | None = None,
    target_url: str | None = None,
    taca_item_id: int | None = None,
    surface: str = "unknown",
    button_id: str = "unknown",
    button_label: str = "unknown",
    position: int | None = None,
    request_id: str | None = None,
    product_snapshot: dict | None = None,
) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps(
            {
                "u": user_id,
                "p": product_key,
                "s": source,
                "c": category_ids or [],
                "l": target_url,
                "i": taca_item_id,
                "v": surface,
                "b": button_id,
                "n": button_label,
                "o": position,
                "r": request_id,
                "m": product_snapshot or {},
                "e": int(time.time()) + 86400,
            }, ensure_ascii=False, separators=(",", ":"),
        ).encode()
    ).decode().rstrip("=")
    signature = hmac.new(_tracking_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_tracking_token(token: str) -> tuple[str, str, str, list[int], str | None, int | None, str, str, str, int | None, str | None] | None:
    try:
        payload, signature = token.split(".", 1)
        expected = hmac.new(_tracking_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["e"] < time.time() or (
            data["p"] not in TOSS_SHOPPING_PRODUCTS and not data.get("l")
        ):
            return None
        return (
            data["u"],
            data["p"],
            data.get("s", "promotion_button"),
            [int(value) for value in data.get("c", [])],
            data.get("l"),
            data.get("i"),
            data.get("v", "unknown"),
            data.get("b", "unknown"),
            data.get("n", "unknown"),
            int(data["o"]) if data.get("o") is not None else None,
            data.get("r"),
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def create_toss_promotion_button(
    product: dict | None = None,
    click_url: str | None = None,
    label: str = TOSS_LIVING_MENU_BUTTON_LABEL,
):
    settings = promotion_settings.read_settings()
    label = settings.menu_button_label or ("🛍️ 오늘의 추천 상품" if settings.mode == "fixed" else _rotating_label(MENU_BUTTON_LABELS))
    return {
        "label": label,
        "action": "message",
        "messageText": "쇼핑 특가",
        "extra": {
            "source": "menu_button",
            "button_id": "toss_promotion_menu_button",
            "button_label": label,
        },
    }


def get_product(product_key: str | None = None) -> dict:
    if product_key and product_key.startswith("fixed_"):
        for item in promotion_settings.read_settings().products:
            if promotion_settings.product_key(item.url) == product_key:
                return item.model_dump()
        return TOSS_SHOPPING_PRODUCTS.get(product_key, {"title": "이전에 등록된 상품", "url": ""})
    return TOSS_SHOPPING_PRODUCTS.get(product_key, TOSS_SHOPPING_PROMOTION)


def create_toss_promotion_quick_reply(kakao_response, product: dict | None = None):
    settings = promotion_settings.read_settings()
    label = settings.quick_reply_label or ("🛍️ 오늘의 추천 상품" if settings.mode == "fixed" else _rotating_label(QUICK_REPLY_LABELS))
    if common.KAKAO_TOSS_PROMOTION_BLOCK_ID:
        return kakao_response.create_quick_reply(
            label=label,
            message_text="쇼핑 특가",
            action="block",
            block_id=common.KAKAO_TOSS_PROMOTION_BLOCK_ID,
            extra={
                "source": "quick_reply",
                "button_id": "toss_promotion_quick_reply",
                "button_label": label,
            },
        )
    return kakao_response.create_quick_reply(
        label=label,
        message_text="쇼핑 특가",
        extra={
            "source": "quick_reply",
            "button_id": "toss_promotion_quick_reply",
            "button_label": label,
        },
    )


def _is_bulk_quantity(title: str) -> bool:
    for amount, unit in _BULK_QUANTITY_PATTERN.findall(title or ""):
        limit = next((value for key, value in _BULK_QUANTITY_LIMITS if key == unit.lower()), None)
        if limit is not None and float(amount.replace(",", "")) > limit:
            return True
    return False


def passes_inline_quality_gate(item: dict) -> bool:
    """Judge a raw Toss candidate for menu-inline exposure."""
    price = item.get("displayPrice") or 0
    if not price or price > INLINE_CARD_MAX_PRICE:
        return False
    if (item.get("discountRate") or 0) < INLINE_CARD_MIN_DISCOUNT_RATE:
        return False
    if item.get("isSoldOut") or not item.get("thumbnailUrl"):
        return False
    return not _is_bulk_quantity(item.get("displayName", ""))


def _is_renderable_inline(product: dict) -> bool:
    return bool(
        product.get("price")
        and product.get("image_url")
        and not product.get("is_sold_out")
    )


def _rotate_fixed_product(
    products: list[tuple[str, dict]], last_exposed: dict[str, object]
) -> tuple[str, dict]:
    """Walk the admin's order, showing what this user has not seen yet.

    한 바퀴를 다 돌면 가장 오래전에 보여준 상품부터 다시 시작한다.
    """
    for key, product in products:
        if key not in last_exposed:
            return key, product
    return min(products, key=lambda pair: last_exposed[pair[0]])


async def record_inline_exposure(
    user_id: str | None, product_key: str, product: dict, request_id: str | None = None
) -> None:
    """Record the exposure only once the card is known to be in the response."""
    try:
        await recommendations.record_exposure(
            user_id, INLINE_CARD_SURFACE, product.get("taca_item_id") or 0,
            product.get("category_ids") or [], product_key=product_key,
            properties={
                "product_name": product["title"],
                "position": 1,
                "selection_mode": product.get("selection_mode") or (
                    "fixed" if product_key.startswith("fixed_") else "algorithm"
                ),
                "settings_revision": product.get("settings_revision"),
            },
            request_id=request_id,
        )
    except Exception:
        logging.getLogger(__name__).exception("failed to record inline product exposure")


async def get_inline_promotion_product(
    user_id: str | None, request_id: str | None = None
) -> tuple[str, dict] | None:
    """Pick at most one product for the menu-inline card, or None when nothing qualifies.

    노출은 카드가 실제로 응답에 들어간 뒤에 record_inline_exposure로 따로 기록한다.
    """
    settings = promotion_settings.read_settings()
    if settings.mode == "fixed":
        # 관리자가 직접 고른 상품은 품질 게이트 대신 렌더 가능 여부만 확인한다.
        try:
            products = await asyncio.wait_for(
                promotion_settings.resolved_fixed_products(settings), timeout=3.5
            )
        except Exception:
            products = promotion_settings.fixed_products(settings)
        renderable = [(key, product) for key, product in products if _is_renderable_inline(product)]
        if not renderable:
            return None
        key, product = _rotate_fixed_product(
            renderable, await recommendations.last_exposure_by_product(user_id, INLINE_CARD_SURFACE)
        )
        TOSS_SHOPPING_PRODUCTS[key] = product
        return key, product

    candidates = [item for item in await _candidate_pool() if passes_inline_quality_gate(item)]
    if not candidates:
        return None
    affinity = await recommendations.category_affinity(user_id)
    recent_ids = await recommendations.recent_item_ids(user_id)
    item = recommendations.rank_candidates(
        candidates, affinity, recent_ids, user_id, INLINE_CARD_SURFACE
    )
    if not item:
        return None
    return await get_live_toss_product(
        user_id, INLINE_CARD_SURFACE,
        preferred_item_id=int(item["tacaItemId"]), request_id=request_id,
        record_exposure=False,
    )


def _trim_product_title(title: str, limit: int = COMMERCE_CARD_TITLE_LIMIT) -> str:
    """Cut a long Toss product name at an option boundary instead of mid-word."""
    if len(title) <= limit:
        return title
    head = title[:limit - 1]
    boundary = head.rfind(",")
    return (head[:boundary] if boundary > limit // 2 else head).rstrip(" ,") + "…"


def inline_product_description(product: dict) -> str:
    """Use the same wording as the product list shown after the entry button."""
    custom = (product.get("description") or "").strip()
    if custom:
        return custom
    if product.get("price") is None:
        return "현재 가격과 구매 조건은 토스에서 확인해주세요."
    return f"{product.get('discount_rate') or 0}% 할인 · 최대할인가 {product['price']:,}원"


def _inline_product_button(product: dict, click_url: str | None) -> dict:
    label = (product.get("button_label") or "구매하러 가기").removesuffix(" · 제휴")
    return {
        "action": "webLink",
        "label": label[:INLINE_CARD_BUTTON_LIMIT],
        "webLinkUrl": click_url or product["url"],
    }


def create_inline_product_output(product: dict, click_url: str | None = None) -> dict:
    """Build the commerceCard output that takes an unused meal slot."""
    price = product.get("price") or 0
    original_price = product.get("original_price") or price
    commerce_card = {
        "title": _trim_product_title(product["title"]),
        "description": inline_product_description(product)[:COMMERCE_CARD_DESCRIPTION_LIMIT],
        "price": original_price,
        "currency": "won",
        "discountedPrice": price,
        "thumbnails": [{"imageUrl": product["image_url"]}],
        "buttons": [_inline_product_button(product, click_url)],
    }
    # discountRate는 discountedPrice가 있어야 노출되고, discount보다 우선 표시된다.
    if product.get("discount_rate"):
        commerce_card["discountRate"] = product["discount_rate"]
    elif original_price > price:
        commerce_card["discount"] = original_price - price
    return {"commerceCard": commerce_card}


def create_toss_shopping_response(product: dict | None = None, click_url: str | None = None):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    product = product or TOSS_SHOPPING_PROMOTION
    card_description = (
        "츠누봇이 토스와 준비한 특가예요 🛍️\n"
        "• 이 링크를 통해서만 할인 혜택을 받을 수 있어요.\n"
        "• 구매 수수료는 챗봇 서버 운영비로 사용됩니다.\n"
        f"{product['discount_rate']}% 할인 · 최대할인가 {product['price']:,}원"
    )
    commerce_card = {
        "title": product["title"],
        "description": card_description,
        "price": product["original_price"],
        "currency": "won",
        "discount": product["discount"],
        "discountRate": product["discount_rate"],
        "discountedPrice": product["price"],
        "thumbnails": [{"imageUrl": product["image_url"]}],
        "buttons": [
            {
                "action": "webLink",
                "label": product["button_label"].removesuffix(" · 제휴"),
                "webLinkUrl": click_url or product["url"],
            }
        ],
    }
    return kakao_response.add_output_to_response(
        {"commerceCard": commerce_card}
    ).get_response()


def create_toss_shopping_list_response(
    products: list[dict], click_urls: list[str | None] | None = None
):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    click_urls = click_urls or [None] * len(products)
    is_fixed = bool(products) and all(p.get("selection_mode") == "fixed" for p in products)
    if is_fixed and any(p.get("price") is None or not p.get("image_url") or p.get("is_sold_out") for p in products):
        kakao_response.add_output_to_response(kakao_response.create_simple_text(
            promotion_settings.FIXED_PROMOTION_INTRO
        ))
        cards = []
        for product, click_url in zip(products, click_urls):
            card = {"title": product["title"][:50],
                    "description": ("품절 · " if product.get("is_sold_out") else "") + (product.get("description") or
                                    (f"{product['discount_rate']}% 할인 · 최대할인가 {product['price']:,}원" if product.get("price") is not None else "현재 가격과 구매 조건은 토스에서 확인해주세요.")),
                    "buttons": [{"action": "webLink", "label": product["button_label"],
                                 "webLinkUrl": click_url or product["url"]}]}
            if product.get("image_url"):
                card["thumbnail"] = {"imageUrl": product["image_url"]}
            cards.append(card)
        for start in range(0, len(cards), COMMERCE_CARDS_PER_ROW):
            row = cards[start:start + COMMERCE_CARDS_PER_ROW]
            card_type = "basicCard" if all("thumbnail" in card for card in row) else "textCard"
            if card_type == "textCard":
                row = [{key: value for key, value in card.items() if key != "thumbnail"} for card in row]
            kakao_response.add_output_to_response(kakao_response.create_carousel(
                row, type=card_type))
        return kakao_response.get_response()
    cards = []
    for product, click_url in zip(products, click_urls):
        cards.append(
            {
                "title": product["title"],
                "description": product.get("description") if is_fixed and product.get("description") else f"{product['discount_rate']}% 할인 · 최대할인가 {product['price']:,}원",
                "price": product["original_price"],
                "currency": "won",
                "discount": product["discount"],
                "discountRate": product["discount_rate"],
                "discountedPrice": product["price"],
                "thumbnails": [{"imageUrl": product["image_url"]}],
                "buttons": [
                    {
                        "action": "webLink",
                        "label": product["button_label"].removesuffix(" · 제휴"),
                        "webLinkUrl": click_url or product["url"],
                    }
                ],
            }
        )
    kakao_response.add_output_to_response(
        kakao_response.create_simple_text(
            promotion_settings.FIXED_PROMOTION_INTRO if is_fixed else
            "츠누봇이 토스와 준비한 특가예요 🛍️\n"
            "• 이 링크를 통해서만 할인 혜택을 받을 수 있어요.\n"
            "• 구매 수수료는 챗봇 서버 운영비로 사용됩니다."
        )
    )
    for start in range(0, len(cards), COMMERCE_CARDS_PER_ROW):
        kakao_response.add_output_to_response(
            kakao_response.create_carousel(
                cards[start : start + COMMERCE_CARDS_PER_ROW],
                type="commerceCard",
            )
        )
    return kakao_response.get_response()
