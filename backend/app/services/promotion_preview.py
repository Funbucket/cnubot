"""Private, opt-in developer preview of the student deal bundle."""
import asyncio
import logging
import os
import re
import uuid

from app.services import (
    product_snapshot, promotion_settings, promotions,
    recommendation_policy, recommendations,
)

logger = logging.getLogger(__name__)
SELECTION_MODE = "student_bundle_preview"
MAX_PRICE = 10000
SNACK_WORDS = ("간식", "과자", "음료", "생수", "탄산", "커피", "차류", "초콜릿",
               "제과", "빵", "젤리", "쿠키", "아이스크림", "시리얼", "견과")
MEAL_WORDS = ("라면", "즉석", "간편", "냉동", "햄", "소시지", "통조림", "만두",
              "즉석밥", "죽", "면류", "떡", "육가공")
LIVING_WORDS = ("세제", "물티슈", "화장지", "구강", "치약", "칫솔", "비누", "청소",
                "세탁", "욕실", "위생", "방향", "탈취", "제습", "생리대", "수세미",
                "봉투", "장갑")


def enabled(user_id: str | None) -> bool:
    developer_id = os.getenv("DEVELOPER_ID", "").strip()
    return bool(
        user_id and developer_id and user_id == developer_id
        and os.getenv("PROMOTION_BUNDLE_PREVIEW_ENABLED", "false").strip().lower()
        in {"true", "1", "on", "yes"}
    )


def _category_tree(snapshot: dict) -> dict[int, list[str]]:
    tree = {}
    def walk(nodes, parents):
        for node in nodes:
            path = parents + [str(node.get("displayName", ""))]
            if node.get("categoryId") is not None:
                tree[int(node["categoryId"])] = path
            walk(node.get("children", []), path)
    walk(snapshot.get("categories", {}).get("success", {}).get("categories", []), [])
    return tree


def _student_sized(title: str, slot: str) -> bool:
    """Reject clearly oversized weight/volume bundles without guessing unknown sizes."""
    packs = re.findall(r"(\d+)\s*(?:개|팩|병|봉|캔)\b", title.lower())
    count = int(packs[-1]) if packs else 1
    grams = promotion_settings.infer_total_weight_g(title, count)
    if grams and grams > 2000:
        return False
    volumes = re.findall(r"(\d+(?:\.\d+)?)\s*(ml|l)(?![a-z])", title.lower())
    if volumes:
        value, unit = volumes[-1]
        liters = float(value) * (0.001 if unit == "ml" else 1) * count
        if liters > (3 if slot == "living" else 6):
            return False
    return True


def select_products(snapshot: dict, publisher_id: str, last_exposed: dict) -> list[tuple[str, dict]]:
    """Select up to three distinct uses from one immutable stored snapshot."""
    tree = _category_tree(snapshot)
    candidates = []
    for item in snapshot.get("items", {}).values():
        if not product_snapshot.available(item, snapshot) or not promotions.passes_inline_quality_gate(item):
            continue
        price = item.get("displayPrice") or 0
        original = item.get("originalPrice") or price
        if price > MAX_PRICE or original <= 0:
            continue
        discount = min(int(item.get("discountRate") or 0), int(100 * max(0, original-price) / original))
        if discount < promotions.INLINE_CARD_MIN_DISCOUNT_RATE:
            continue
        item_id = int(item["tacaItemId"])
        url = snapshot.get("links", {}).get(f"{item_id}:{publisher_id}")
        if not url:
            continue
        food = recommendation_policy.classify(item, tree, "food")
        living = recommendation_policy.classify(item, tree, "living")
        policy = food or living
        if not policy:
            continue
        names = [name for path in policy["category_paths"] for name in path]
        if recommendations._is_student_excluded({**item, "_category_names": names}):
            continue
        category_text = " ".join(names[1:])
        if food:
            if any(word in category_text for word in SNACK_WORDS):
                slot = "snack"
            elif any(word in category_text for word in MEAL_WORDS):
                slot = "meal"
            else:
                continue
            collection_id = "food"
        elif any(word in category_text for word in LIVING_WORDS):
            slot, collection_id = "living", "living"
        else:
            continue
        if not _student_sized(item["displayName"], slot):
            continue
        key = f"preview_toss_item_{item_id}"
        product = promotions._add_automatic_merchandising_fields({
            "title": item["displayName"], "price": price, "original_price": original,
            "discount_rate": discount, "image_url": item["thumbnailUrl"], "url": url,
            "review_score": item.get("reviewScore"), "review_count": item.get("reviewCount"),
            "taca_item_id": item_id, "category_ids": item.get("categoryIds", []),
            "category_names": list(dict.fromkeys(names)), "collection_id": collection_id,
            "selection_mode": SELECTION_MODE, "button_label": "특가 바로가기",
            "preview_slot": slot, "preview_family": policy["family"],
        })
        candidates.append((key, product))
    def rank(pair):
        key, product = pair
        seen = last_exposed.get(key)
        return (seen is not None, seen.timestamp() if seen else 0, product["price"],
                -(product.get("review_score") or 0), -product["discount_rate"], product["taca_item_id"])
    candidates.sort(key=rank)
    selected, families = [], set()
    for slot in ("meal", "snack", "living"):
        match = next((p for p in candidates if p[1]["preview_slot"] == slot
                      and p[1]["preview_family"] not in families), None)
        if match:
            selected.append(match)
            families.add(match[1]["preview_family"])
    for pair in candidates:
        if len(selected) >= 3:
            break
        if pair[1]["preview_family"] not in families:
            selected.append(pair)
            families.add(pair[1]["preview_family"])
    return selected


async def pick(user_id: str, surface: str) -> tuple[list[tuple[str, dict]], list[str], str] | None:
    if not enabled(user_id):
        return None
    snapshot = await asyncio.to_thread(product_snapshot.read)
    history = await recommendations.last_exposure_by_product(user_id, surface)
    pairs = select_products(snapshot, os.getenv("TOSS_PUBLISHER_ID", "").strip(), history)
    if not pairs:
        return None
    revision = promotion_settings.read_settings().revision
    request_id = str(uuid.uuid4())
    click_urls = []
    for position, (key, product) in enumerate(pairs, 1):
        product["settings_revision"] = revision
        promotions.TOSS_SHOPPING_PRODUCTS[key] = dict(product)
        token = promotions.create_tracking_token(
            user_id, key, surface, category_ids=product["category_ids"],
            target_url=product["url"], taca_item_id=product["taca_item_id"], surface=surface,
            button_id="student_bundle_product", button_label=product["button_label"],
            position=position, request_id=request_id,
            product_snapshot={"is_preview": True, **{k: product.get(k) for k in (
                "title", "button_label", "settings_revision", "selection_mode", "collection_id")}},
        )
        click_urls.append(f"{promotions.common.SERVER_URL}/promotions/toss-shopping/click?token={token}")
    return pairs, click_urls, request_id


async def record(user_id: str, pairs: list[tuple[str, dict]], request_id: str, surface: str,
                 *, daily_cap: bool) -> bool:
    items = [{
        "product_key": key, "taca_item_id": product["taca_item_id"],
        "category_ids": product["category_ids"],
        "properties": {
            "product_name": product["title"], "collection_id": product["collection_id"],
            "selection_mode": SELECTION_MODE, "is_preview": True, "settings_revision": product["settings_revision"],
            "position": position, "preview_slot": product["preview_slot"],
            "bundle_size": len(pairs),
        },
    } for position, (key, product) in enumerate(pairs, 1)]
    try:
        return await recommendations.record_bundle_exposure(
            user_id, surface, items, request_id, daily_cap=daily_cap)
    except Exception:
        logger.exception("failed to record developer bundle exposure")
        return False
