"""Kakao product card rendering; selection and tracking belong to promotions."""
from app.utils import kakao_json_response
from app.services import promotion_settings

COMMERCE_CARDS_PER_ROW = 3
INLINE_CARD_BUTTON_LIMIT = 14
COMMERCE_CARD_TITLE_LIMIT = 30
COMMERCE_CARD_DESCRIPTION_LIMIT = 40
# A weak rating reads worse than no rating at all, so keep the bar high.
REVIEW_MIN_SCORE = 4.0
REVIEW_MIN_COUNT = 50
INLINE_REVIEW_MIN_COUNT = 100
INLINE_DESCRIPTION_LINE_LIMIT = 2


def _trim_product_title(title: str, limit: int = COMMERCE_CARD_TITLE_LIMIT) -> str:
    """Cut a long Toss product name at an option boundary instead of mid-word."""
    if len(title) <= limit:
        return title
    head = title[:limit - 1]
    boundary = head.rfind(",")
    return (head[:boundary] if boundary > limit // 2 else head).rstrip(" ,") + "…"


def inline_product_description(product: dict) -> str:
    """Lead with the rating: a first-time viewer weighs trust over unit prices."""
    return _fit_callouts(
        [review_suffix(product, INLINE_REVIEW_MIN_COUNT),
         unit_price_suffix(product),
         gram_price_suffix(product)],
        max_lines=INLINE_DESCRIPTION_LINE_LIMIT,
    )


def unit_price_suffix(product: dict) -> str:
    """Return an optional per-item price callout for fixed products."""
    if not product.get("show_unit_price"):
        return ""
    count = product.get("unit_count")
    price = product.get("price")
    if not isinstance(count, int) or count <= 1 or not isinstance(price, (int, float)) or price <= 0:
        return ""
    return f"\n🏷️ 1개당 {round(price / count):,}원"


def gram_price_suffix(product: dict) -> str:
    """Return an optional per-100g price callout for fixed products."""
    if not product.get("show_gram_price"):
        return ""
    grams = product.get("total_weight_g")
    price = product.get("price")
    if not isinstance(grams, int) or grams <= 0 or not isinstance(price, (int, float)) or price <= 0:
        return ""
    return f"\n⚖️ 100g당 {round(price / grams * 100):,}원"


def review_suffix(product: dict, min_count: int = REVIEW_MIN_COUNT) -> str:
    """Return a Toss rating callout, but only when it is strong enough to help."""
    if not product.get("show_review", True):
        return ""
    score = product.get("review_score")
    count = product.get("review_count")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return ""
    if isinstance(count, bool) or not isinstance(count, int):
        return ""
    if score < REVIEW_MIN_SCORE or count < min_count:
        return ""
    # Spelling the count out in full costs at most 3 characters more than a
    # 만 abbreviation, and the two-line inline budget absorbs that.
    return f"\n⭐️ {score:.1f} ({count:,})"


def _fit_callouts(suffixes: list[str], max_lines: int | None = None) -> str:
    """Keep callouts in priority order, dropping the ones that blow the budget."""
    kept: list[str] = []
    used = 0
    for line in (suffix.lstrip("\n") for suffix in suffixes):
        if not line or (max_lines is not None and len(kept) >= max_lines):
            continue
        cost = len(line) + bool(kept)
        if used + cost > COMMERCE_CARD_DESCRIPTION_LIMIT:
            continue
        kept.append(line)
        used += cost
    return "\n".join(kept)


def fixed_product_description(product: dict) -> str:
    # commerceCard already renders original price, sale price, and discount
    # rate above this area. The description is reserved for unit prices first —
    # the carousel is a comparison surface — and then the rating if it still fits.
    return _fit_callouts(
        [unit_price_suffix(product), gram_price_suffix(product), review_suffix(product)]
    )


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
    target = promotion_settings.read_collection("food")
    commerce_card["buttons"].append({
        "action": "message", "label": "먹거리 더 보기", "messageText": target.message_text,
        "extra": {"source": "menu_inline_more", "button_id": "food_inline_more",
                  "button_label": "먹거리 더 보기", "collection_id": "food"},
    })
    # discountRate는 discountedPrice가 있어야 노출되고, discount보다 우선 표시된다.
    if product.get("discount_rate"):
        commerce_card["discountRate"] = product["discount_rate"]
    elif original_price > price:
        commerce_card["discount"] = original_price - price
    return {"commerceCard": commerce_card}


def create_toss_shopping_response(product: dict, click_url: str | None = None):
    kakao_response = kakao_json_response.KakaoJsonResponse()
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
    products: list[dict], click_urls: list[str | None] | None = None,
    collection_id: str | None = None,
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
                    "description": ("품절 · " if product.get("is_sold_out") else "") + fixed_product_description(product),
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
        if collection_id in {"food", "living"}:
            other = "living" if collection_id == "food" else "food"
            target = promotion_settings.read_collection(other)
            kakao_response.add_quick_replies([kakao_response.create_quick_reply(target.label, target.message_text)])
        return kakao_response.get_response()
    cards = []
    for product, click_url in zip(products, click_urls):
        cards.append(
            {
                "title": product["title"],
                "description": fixed_product_description(product) if is_fixed else f"{product['discount_rate']}% 할인 · 최대할인가 {product['price']:,}원",
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
    if collection_id in {"food", "living"}:
        other = "living" if collection_id == "food" else "food"
        target = promotion_settings.read_collection(other)
        kakao_response.add_quick_replies([kakao_response.create_quick_reply(target.label, target.message_text)])
    return kakao_response.get_response()
