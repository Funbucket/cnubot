from app.utils import common, kakao_json_response

PROMOTION_EXPERIMENT_KEY = "snack_product_comparison_v1"

TOSS_SHOPPING_PRODUCTS = {
    "yellow_cheese_buttering": {
    "title": "해태 버터링 딥황치즈맛 4개",
    "button_label": "🍪 황치즈 버터링 특가",
    "quick_reply_label": "🍪 황치즈 버터링 특가",
    "description": "🍪 황치즈 덕후 주목! 첫 구매 3,000원 추가 할인",
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
        "title": "종근당건강 락토핏 골드, 140포, 2개 + 증정 락토핏 골드, 30포 + 증정 아임비타 면역비타민C, 30포",
        "button_label": "💊 유산균 특가",
        "quick_reply_label": "💊 유산균 특가",
        "description": "💊 매일 챙기는 유산균, 무료배송 특가로 만나보세요",
        "price": 51987,
        "discount": 96413,
        "discount_rate": 64,
        "url": "https://sharelink.toss.im/links/products/2570438725?originSurface=recommended_products&originSectionCode=main&originPosition=47&originPage=1",
        "image_url": "https://resources-fe.toss.im/image-optimize/width=2400,quality=90/https%3A%2F%2Fshopping.toss.im%2Flive%2Ftemp%2F2026-08-03%2F74828108-78eb-4328-bf27-62b32a559495.jpeg",
    },
}

TOSS_SHOPPING_PROMOTION = TOSS_SHOPPING_PRODUCTS["yellow_cheese_buttering"]


def create_toss_promotion_button(product: dict | None = None):
    product = product or TOSS_SHOPPING_PROMOTION
    label = product["button_label"]
    if common.KAKAO_TOSS_PROMOTION_BLOCK_ID:
        return {
            "label": label,
            "action": "block",
            "blockId": common.KAKAO_TOSS_PROMOTION_BLOCK_ID,
            "messageText": "쇼핑 특가",
        }
    return {
        "label": label,
        "action": "webLink",
        "webLinkUrl": product["url"],
    }


def get_product(product_key: str | None = None) -> dict:
    return TOSS_SHOPPING_PRODUCTS.get(product_key, TOSS_SHOPPING_PROMOTION)


def create_toss_promotion_quick_reply(kakao_response):
    if common.KAKAO_TOSS_PROMOTION_BLOCK_ID:
        return kakao_response.create_quick_reply(
            label="🛍️ 쇼핑 특가",
            message_text="쇼핑 특가",
            action="block",
            block_id=common.KAKAO_TOSS_PROMOTION_BLOCK_ID,
        )
    return kakao_response.create_quick_reply(
        label="🛍️ 쇼핑 특가",
        message_text="쇼핑 특가",
    )


def create_toss_shopping_response(product: dict | None = None):
    kakao_response = kakao_json_response.KakaoJsonResponse()
    product = product or TOSS_SHOPPING_PROMOTION
    commerce_card = {
        "title": product["title"],
        "description": product["description"],
        "price": product["price"],
        "currency": "won",
        "discount": product["discount"],
        "discountRate": product["discount_rate"],
        "thumbnails": [{"imageUrl": product["image_url"]}],
        "buttons": [
            {
                "action": "webLink",
                "label": product["button_label"],
                "webLinkUrl": product["url"],
            }
        ],
    }
    return kakao_response.add_output_to_response(
        {"commerceCard": commerce_card}
    ).get_response()
