import base64
import hashlib
import hmac
import json
import os
import time

from app.utils import common, kakao_json_response
from app.services import toss_sharelink
from app.services import recommendations

PROMOTION_EXPERIMENT_KEY = "snack_product_comparison_v3"
DEFAULT_PROMOTION_PRODUCT_KEY = "pepsi_lime"

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


async def get_live_toss_product(
    user_id: str | None = None,
    surface: str = "default",
    preferred_item_id: int | None = None,
) -> tuple[str, dict]:
    candidates = await toss_sharelink.best_selling(size=10)
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
    }
    await recommendations.record_exposure(
        user_id,
        surface,
        item_id,
        TOSS_SHOPPING_PRODUCTS[product_key]["category_ids"],
    )
    return product_key, TOSS_SHOPPING_PRODUCTS[product_key]


async def get_live_toss_products(
    user_id: str | None = None,
    surface: str = "quick_reply",
    limit: int = 5,
) -> list[tuple[str, dict]]:
    candidates = await toss_sharelink.best_selling(size=max(limit * 2, 10))
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
            }
            product = TOSS_SHOPPING_PRODUCTS[product_key]
            await recommendations.record_exposure(user_id, surface, item_id, category_ids)
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
                "e": int(time.time()) + 86400,
            }
        ).encode()
    ).decode().rstrip("=")
    signature = hmac.new(_tracking_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def read_tracking_token(token: str) -> tuple[str, str, str, list[int], str | None, int | None, str] | None:
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
        )
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def create_toss_promotion_button(product: dict | None = None, click_url: str | None = None):
    product = product or TOSS_SHOPPING_PROMOTION
    label = product["button_label"]
    if common.KAKAO_TOSS_PROMOTION_BLOCK_ID:
        return {
            "label": label,
            "action": "block",
            "blockId": common.KAKAO_TOSS_PROMOTION_BLOCK_ID,
            "messageText": "쇼핑 특가",
            "extra": {"source": "menu_button"},
        }
    return {
        "label": label,
        "action": "webLink",
        "webLinkUrl": click_url or product["url"],
    }


def get_product(product_key: str | None = None) -> dict:
    return TOSS_SHOPPING_PRODUCTS.get(product_key, TOSS_SHOPPING_PROMOTION)


def create_toss_promotion_quick_reply(kakao_response, product: dict | None = None):
    label = (product or {}).get("button_label", "🛒 기숙사·자취생 특가")
    if common.KAKAO_TOSS_PROMOTION_BLOCK_ID:
        return kakao_response.create_quick_reply(
            label=label,
            message_text="쇼핑 특가",
            action="block",
            block_id=common.KAKAO_TOSS_PROMOTION_BLOCK_ID,
            extra={"source": "quick_reply"},
        )
    return kakao_response.create_quick_reply(
        label=label,
        message_text="쇼핑 특가",
    )


def create_toss_shopping_response(product: dict | None = None, click_url: str | None = None):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    product = product or TOSS_SHOPPING_PROMOTION
    card_description = (
        "구매 수수료는 챗봇 서버 운영비로 사용됩니다.\n"
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
                "label": product["button_label"],
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
    cards = []
    for product, click_url in zip(products, click_urls):
        cards.append(
            {
                "title": product["title"],
                "description": f"{product['discount_rate']}% 할인 · 최대할인가 {product['price']:,}원",
                "price": product["original_price"],
                "currency": "won",
                "discount": product["discount"],
                "discountRate": product["discount_rate"],
                "discountedPrice": product["price"],
                "thumbnails": [{"imageUrl": product["image_url"]}],
                "buttons": [
                    {
                        "action": "webLink",
                        "label": product["button_label"],
                        "webLinkUrl": click_url or product["url"],
                    }
                ],
            }
        )
    kakao_response.add_output_to_response(
        kakao_response.create_simple_text(
            "구매 수수료는 챗봇 서버 운영비로 사용됩니다."
        )
    )
    return kakao_response.add_output_to_response(
        kakao_response.create_carousel(cards, type="commerceCard")
    ).get_response()
