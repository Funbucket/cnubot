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
# 자동 선정 응답의 고지. 고정 상품은 promotion_settings.FIXED_PROMOTION_INTRO를 쓴다.
ALGORITHM_PROMOTION_INTRO = (
    "츠누봇이 토스와 준비한 특가예요 🛍️\n"
    "• 이 링크를 통해서만 할인 혜택을 받을 수 있어요.\n"
    "• 구매 수수료는 챗봇 서버 운영비로 사용됩니다."
)


def _trim_product_title(title: str, limit: int = COMMERCE_CARD_TITLE_LIMIT) -> str:
    """Cut a long Toss product name at an option boundary instead of mid-word."""
    if len(title) <= limit:
        return title
    head = title[:limit - 1]
    boundary = head.rfind(",")
    return (head[:boundary] if boundary > limit // 2 else head).rstrip(" ,") + "…"


def product_description(product: dict, *, review_min_count: int = REVIEW_MIN_COUNT,
                        max_lines: int | None = None) -> str:
    """Build the description for any product card, in one fixed callout order.

    commerceCard already renders original price, sale price, and discount rate
    above this area, so the description leads with unit prices — every product
    surface is a comparison surface — and shows the rating if it still fits.
    Surfaces only vary the budget (``max_lines``) and how many reviews earn a
    rating (``review_min_count``); they must not reorder the callouts.
    """
    return _fit_callouts(
        [unit_price_suffix(product), gram_price_suffix(product),
         review_suffix(product, review_min_count)],
        max_lines=max_lines,
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


def product_link_button(product: dict, click_url: str | None, *, label_limit: int | None = None,
                        keep_affiliate_suffix: bool = False) -> dict:
    """The single 'go buy' webLink button shared by every product card."""
    label = product.get("button_label") or "구매하러 가기"
    if not keep_affiliate_suffix:
        label = label.removesuffix(" · 제휴")
    return {
        "action": "webLink",
        "label": label[:label_limit] if label_limit else label,
        "webLinkUrl": click_url or product["url"],
    }


def commerce_card(product: dict, click_url: str | None, description: str, title: str) -> dict:
    """The commerceCard fields every product carousel shares.

    Callers add the discount fields themselves: the surfaces disagree on when a
    discount is worth rendering, and only the price block differs between them.
    """
    price = product.get("price") or 0
    return {
        "title": title,
        "description": description,
        "price": product.get("original_price") or price,
        "currency": "won",
        "discountedPrice": price,
        "thumbnails": [{"imageUrl": product["image_url"]}],
        "buttons": [product_link_button(product, click_url)],
    }


def add_today_deals_quick_reply(kakao_response, collection_id: str | None) -> None:
    """Show today's-deals entry before collection navigation."""
    if collection_id not in {"food", "living"}:
        return
    kakao_response.add_quick_replies([
        kakao_response.create_quick_reply(
            "🔥 오늘 특가",
            "오늘 특가",
            extra={"source": "quick_reply", "button_id": "today_deals_quick_reply",
                   "button_label": "🔥 오늘 특가", "collection_id": "today_deals"},
        )
    ])


def add_collection_quick_reply(kakao_response, collection_id: str | None) -> None:
    """Add collection navigation without repeating the collection just viewed."""
    if collection_id == "today_deals":
        food = promotion_settings.read_collection("food")
        living = promotion_settings.read_collection("living")
        kakao_response.add_quick_replies([
            kakao_response.create_quick_reply(
                food.label, food.message_text,
                extra={"source": "quick_reply", "button_id": "toss_promotion_quick_reply_food",
                       "button_label": food.label, "collection_id": "food"},
            ),
            kakao_response.create_quick_reply(
                living.label, living.message_text,
                extra={"source": "quick_reply", "button_id": "toss_promotion_quick_reply",
                       "button_label": living.label, "collection_id": "living"},
            ),
        ])
        return
    if collection_id not in {"food", "living"}:
        return
    target_ids = ("food", "living") if collection_id == "today_deals" else (
        "living" if collection_id == "food" else "food",
    )
    kakao_response.add_quick_replies([
        kakao_response.create_quick_reply(
            (target := promotion_settings.read_collection(target_id)).label,
            target.message_text,
            extra={"source": "quick_reply", "button_id": f"toss_promotion_quick_reply_{target_id}",
                   "button_label": target.label, "collection_id": target_id},
        )
        for target_id in target_ids
    ])


def add_refresh_quick_reply(kakao_response, collection_id: str | None, product_count: int) -> None:
    """Add refresh whenever the result contains at least one product."""
    if product_count <= 0 or collection_id not in {"food", "living", "today_deals"}:
        return
    label = "새로고침"
    message_text = ("오늘 특가" if collection_id == "today_deals"
                    else promotion_settings.read_collection(collection_id).message_text)
    kakao_response.add_quick_replies([
        kakao_response.create_quick_reply(
            label,
            message_text,
            extra={"source": "promotion_refresh", "button_id": "promotion_refresh",
                   "button_label": label, "collection_id": collection_id},
        )
    ])


def create_inline_product_output(product: dict, click_url: str | None = None) -> dict:
    """Build the commerceCard output that takes an unused meal slot."""
    card = commerce_card(
        product, click_url,
        description=product_description(
            product, review_min_count=INLINE_REVIEW_MIN_COUNT,
            max_lines=INLINE_DESCRIPTION_LINE_LIMIT)[:COMMERCE_CARD_DESCRIPTION_LIMIT],
        title=_trim_product_title(product["title"]),
    )
    card["buttons"] = [product_link_button(product, click_url, label_limit=INLINE_CARD_BUTTON_LIMIT)]
    collection_id = product.get("collection_id") or "food"
    target = promotion_settings.read_collection(collection_id)
    more_label = "먹거리 더 보기" if collection_id == "food" else "꿀템 더 보기"
    card["buttons"].append({
        "action": "message", "label": more_label, "messageText": target.message_text,
        "extra": {"source": "menu_inline_more", "button_id": f"{collection_id}_inline_more",
                  "button_label": more_label, "collection_id": collection_id},
    })
    # discountRate는 discountedPrice가 있어야 노출되고, discount보다 우선 표시된다.
    if product.get("discount_rate"):
        card["discountRate"] = product["discount_rate"]
    elif card["price"] > card["discountedPrice"]:
        card["discount"] = card["price"] - card["discountedPrice"]
    return {"commerceCard": card}


def _algorithm_commerce_card(product: dict, click_url: str | None, description: str) -> dict:
    """An algorithm-picked card always knows its discount, so always render it."""
    card = commerce_card(product, click_url, description=description, title=product["title"])
    card["discount"] = product["discount"]
    card["discountRate"] = product["discount_rate"]
    return card


def create_toss_shopping_response(product: dict, click_url: str | None = None):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    card = _algorithm_commerce_card(
        product, click_url, description=product_description(product))
    return kakao_response.add_output_to_response({"commerceCard": card}).get_response()


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
            # FIXED_PROMOTION_INTRO에는 제휴 고지가 없어서 버튼의 ` · 제휴`를 남긴다.
            card = {"title": product["title"][:50],
                    "description": ("품절 · " if product.get("is_sold_out") else "") + product_description(product),
                    "buttons": [product_link_button(product, click_url, keep_affiliate_suffix=True)]}
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
        add_today_deals_quick_reply(kakao_response, collection_id)
        add_collection_quick_reply(kakao_response, collection_id)
        add_refresh_quick_reply(kakao_response, collection_id, len(products))
        return kakao_response.get_response()
    cards = [
        _algorithm_commerce_card(
            product, click_url,
            description=product_description(product))
        for product, click_url in zip(products, click_urls)
    ]
    kakao_response.add_output_to_response(
        kakao_response.create_simple_text(
            promotion_settings.FIXED_PROMOTION_INTRO if is_fixed else ALGORITHM_PROMOTION_INTRO
        )
    )
    for start in range(0, len(cards), COMMERCE_CARDS_PER_ROW):
        kakao_response.add_output_to_response(
            kakao_response.create_carousel(
                cards[start : start + COMMERCE_CARDS_PER_ROW],
                type="commerceCard",
            )
        )
    add_today_deals_quick_reply(kakao_response, collection_id)
    add_collection_quick_reply(kakao_response, collection_id)
    add_refresh_quick_reply(kakao_response, collection_id, len(products))
    return kakao_response.get_response()
