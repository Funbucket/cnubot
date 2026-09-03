from app.utils import common, kakao_json_response


TOSS_SHOPPING_PROMOTION = {
    "title": "해태 버터링 딥황치즈맛 4개",
    "button_label": "🧀 황치즈 버터링 특가",
    "quick_reply_label": "🧀 황치즈 버터링 특가",
    "description": "🧀 황치즈 덕후 주목! 첫 구매 3,000원 추가 할인",
    "price": 14500,
    "discount": 4700,
    "discount_rate": 24,
    "url": "https://toss.im/_m/FLJEEeY4",
    "image_url": (
        "https://resources-fe.toss.im/image-optimize/width=2400,quality=90/"
        "https%3A%2F%2Fshopping.toss.im%2Flive%2Ftemp%2F2026-08-26%2F"
        "e51d1317-1639-4907-9f86-5f45118c732f.png"
    ),
}


def create_toss_promotion_button(label: str | None = None):
    label = label or TOSS_SHOPPING_PROMOTION["button_label"]
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
        "webLinkUrl": TOSS_SHOPPING_PROMOTION["url"],
    }


def create_toss_promotion_quick_reply(kakao_response):
    if common.KAKAO_TOSS_PROMOTION_BLOCK_ID:
        return kakao_response.create_quick_reply(
            label=TOSS_SHOPPING_PROMOTION["quick_reply_label"],
            message_text="쇼핑 특가",
            action="block",
            block_id=common.KAKAO_TOSS_PROMOTION_BLOCK_ID,
        )
    return kakao_response.create_quick_reply(
        label=TOSS_SHOPPING_PROMOTION["quick_reply_label"],
        message_text="쇼핑 특가",
    )


def create_toss_shopping_response():
    kakao_response = kakao_json_response.KakaoJsonResponse()
    product = TOSS_SHOPPING_PROMOTION
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
                "label": "🛒 특가로 구매하기",
                "webLinkUrl": product["url"],
            }
        ],
    }
    return kakao_response.add_output_to_response(
        {"commerceCard": commerce_card}
    ).get_response()
