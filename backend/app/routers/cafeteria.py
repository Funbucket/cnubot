import os
import logging
import uuid

from app.schemas.kakao_request import KakaoRequest
from app.services import cafeteria, experiments, promotions
from app.utils import common, kakao_json_response
from fastapi import APIRouter, Body, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse

SHOW_BREAKFAST_KEY = "show_breakfast"
DISABLED_VALUES = {"0", "false", "off", "no"}

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/schedule")
async def get_schedule(req: KakaoRequest | None = Body(default=None)):
    """
    return: 식당 시간표 (static meal_schedule.json + 동적 운영 날짜 추가)
    """
    user_id = req.userRequest.user.id if req and req.userRequest.user else None
    utterance = req.userRequest.utterance.strip() if req else ""
    if _is_dorm_crowding_utterance(utterance):
        return await get_dorm_crowding()

    schedule_data = await common.load_data(cafeteria.MEAL_SCHEDULE_PATH)
    dorm_hours = await cafeteria.dorm_meal_hours()
    for cafeteria_data in schedule_data:
        place = cafeteria_data.get("place")
        # 기숙사 운영시간은 크롤링 값이 최신이므로 정적 파일보다 우선한다.
        if place == "dorm" and dorm_hours:
            cafeteria_data["hours"] = dorm_hours
        if not cafeteria_data.get("date"):
            operating_date = await common.get_operating_date_for_place(place)
            if operating_date:
                cafeteria_data["date"] = operating_date

    response = cafeteria.create_schedule_response(schedule_data)
    await _record_promotion_button_exposures(user_id, response)
    return JSONResponse(response)


@router.post("/menu/today")
async def get_today_menu(req: KakaoRequest):
    """
    req: ex) "기숙사", "제2학생회관", "제3학생회관", "상록회관", "생활과학대학"
    return: 오늘의 메뉴, 요일 퀵리플라이
    """
    utterance = req.userRequest.utterance.strip()
    if _is_dorm_crowding_utterance(utterance):
        return await get_dorm_crowding()

    place = utterance
    current_kst = common.get_current_kr_time()
    today_weekday = current_kst.weekday()  # 0: 월요일, 1: 화요일, ..., 6: 일요일
    kor_day = common.get_kor_day(today_weekday)

    place_key = common.get_eng_place(place)
    data = await common.load_data(str(common.get_menu_data_path(place_key)))
    menu_data = common.get_menu_by_day(data, kor_day)
    if not menu_data:
        raise HTTPException(status_code=404, detail="해당 요일에 메뉴가 없습니다.")

    response = await _menu_response(req, kor_day, menu_data, place, place_key)
    return JSONResponse(response)


@router.post("/dorm/crowding")
async def get_dorm_crowding():
    """
    return: 기숙사 식당 현재 인원/입장 가능 인원
    """
    try:
        response = await run_in_threadpool(cafeteria.get_dorm_crowding_response)
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="기숙사 혼잡도 정보를 가져오지 못했습니다."
        ) from exc
    return JSONResponse(response)


@router.post("/menu/day")
async def get_menu_by_day(req: KakaoRequest):
    """
    req: ex) "월요일기숙사", "월요일제2학생회관"
    return: 요청한 요일의 메뉴
    """
    utterance = req.userRequest.utterance.strip()  # 예: "월요일기숙사"
    kor_day = utterance[:3]  # 예: "월요일"
    place = utterance[3:]  # 예: "기숙사"

    place_key = common.get_eng_place(place)

    try:
        data = await common.load_data(str(common.get_menu_data_path(place_key)))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="데이터 파일을 찾을 수 없습니다.")

    menu_data = common.get_menu_by_day(data, kor_day)
    if not menu_data:
        kakao_response = kakao_json_response.KakaoJsonResponse()
        simple_text = kakao_response.create_simple_text("운영 중인 메뉴가 없어요 🥲")
        kakao_response.add_output_to_response(simple_text)

        return kakao_response.get_response()

    response = await _menu_response(req, kor_day, menu_data, place, place_key)
    return JSONResponse(response)


@router.get("/images/{image_name}")
async def get_image(image_name: str):
    """
    image_name: 이미지 파일 이름 (예: hall_1_menu.png)
    return: 이미지 파일
    """
    file_path = f"app/static/images/{image_name}"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다.")


async def _menu_response(
    req: KakaoRequest, kor_day: str, menu_data: dict, place: str, place_key: str
) -> dict:
    """Build a menu response, placing the inline product card when it fits."""
    user_id = req.userRequest.user.id if req.userRequest.user else None
    chosen = None if _wants_breakfast(req) else await _pick_inline_product(user_id)
    inline_product = {}
    if chosen:
        product_key, product, click_url, request_id = chosen
        inline_product = {
            "inline_product_output": promotions.create_inline_product_output(product, click_url),
        }
        # 시간표의 "식단 보기"는 오늘 날짜 발화로 /menu/day를 타므로 요일로 판단한다.
        if place_key == "dorm" and kor_day == common.get_today_in_korean():
            menu_data, inline_product = await _replace_finished_breakfast(
                menu_data, inline_product, place
            )

    response = cafeteria.create_menu_response(kor_day, menu_data, place, **inline_product)

    placed = bool(chosen) and _inline_card_placed(response, inline_product)
    if placed:
        await promotions.record_inline_exposure(user_id, product_key, product, request_id)
    await _record_menu_view(user_id, place_key, kor_day, placed)
    await _record_promotion_button_exposures(user_id, response)
    return response


async def _record_menu_view(
    user_id: str | None, place_key: str, kor_day: str, inline_card: bool
) -> None:
    """Log every menu view, ad or not, so guardrails are not measured on ads only."""
    try:
        await experiments.record_funnel_event(
            user_id,
            "menu_view",
            source=place_key,
            properties={"place": place_key, "day": kor_day, "inline_card": inline_card},
        )
    except Exception:
        logger.exception("failed to record menu view")


def _inline_card_placed(response: dict, inline_product: dict) -> bool:
    """Only a card that survived placement counts as an exposure."""
    output = inline_product.get("inline_product_output")
    return any(rendered is output for rendered in response["template"]["outputs"])


def _wants_breakfast(req: KakaoRequest) -> bool:
    """The restore button asks for this one response only — nothing is remembered."""
    if not req.action:
        return False
    for payload in (req.action.clientExtra, req.action.extra):
        if (payload or {}).get(SHOW_BREAKFAST_KEY):
            return True
    return False


async def _replace_finished_breakfast(
    menu_data: dict, inline_product: dict, place: str
) -> tuple[dict, dict]:
    """Give the finished breakfast slot to the product card, restorable on demand.

    아침은 조회가 적고 제공이 끝나면 정보 가치도 없어서 당일에 한해 광고로 대체한다.
    점심·저녁은 광고가 과해지므로 대체하지 않는다.
    """
    if not any(meal["menu"] for meal in menu_data.get("breakfast") or []):
        return menu_data, inline_product
    hours = await cafeteria.dorm_meal_hours()
    if not cafeteria.is_meal_time_over(hours, "breakfast"):
        return menu_data, inline_product

    restore_button = {
        "action": "message",
        "label": "아침 식단 보기",
        "messageText": place,
        "extra": {SHOW_BREAKFAST_KEY: True},
    }
    card = inline_product.get("inline_product_output", {}).get("commerceCard")
    if card is not None:
        card.setdefault("buttons", []).append(restore_button)
        card["buttonLayout"] = "vertical"
    return {**menu_data, "breakfast": []}, inline_product


def _inline_card_enabled(user_id: str | None) -> bool:
    """Menu-inline product cards are on for everyone unless narrowed or switched off.

    PROMOTION_INLINE_CARD_ENABLED=false 로 즉시 되돌릴 수 있고,
    PROMOTION_INLINE_CARD_USER_IDS 를 채우면 그 사용자에게만 노출된다.
    """
    if not user_id:
        return False
    if os.getenv("PROMOTION_INLINE_CARD_ENABLED", "true").strip().lower() in DISABLED_VALUES:
        return False
    allowed = {
        value.strip()
        for value in os.getenv("PROMOTION_INLINE_CARD_USER_IDS", "").split(",")
        if value.strip()
    }
    return not allowed or user_id in allowed


async def _pick_inline_product(user_id: str | None):
    if not _inline_card_enabled(user_id):
        return None
    request_id = str(uuid.uuid4())
    try:
        chosen = await promotions.get_inline_promotion_product(user_id, request_id)
    except Exception:
        logger.exception("failed to pick inline promotion product")
        return None
    if not chosen:
        return None
    product_key, product = chosen
    try:
        token = promotions.create_tracking_token(
            user_id, product_key, "menu_inline",
            category_ids=product.get("category_ids"), target_url=product.get("url"),
            taca_item_id=product.get("taca_item_id"),
            surface=promotions.INLINE_CARD_SURFACE,
            button_id="toss_promotion_menu_inline_card",
            button_label="토스에서 보기",
            position=1, request_id=request_id,
            product_snapshot={key: product.get(key) for key in
                              ("title", "button_label", "settings_revision", "selection_mode")},
        )
        click_url = f"{common.SERVER_URL}/promotions/toss-shopping/click?token={token}"
    except Exception:
        logger.exception("failed to create inline promotion tracking token")
        return None
    return product_key, product, click_url, request_id


def _is_dorm_crowding_utterance(utterance: str) -> bool:
    normalized = utterance.replace(" ", "")
    return "기숙사" in normalized and "혼잡도" in normalized


async def _record_promotion_button_exposures(user_id: str | None, response: dict) -> None:
    """Record promotion buttons that were included in the response sent to a user."""
    seen: set[tuple[str, str]] = set()
    request_id = str(uuid.uuid4())

    def walk(value):
        if isinstance(value, dict):
            extra = value.get("extra")
            if isinstance(extra, dict) and extra.get("source") in {"quick_reply", "menu_button"}:
                key = (extra.get("source", "unknown"), extra.get("button_id", "unknown"))
                if key not in seen:
                    seen.add(key)
                    yield extra
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for extra in walk(response):
        try:
            await experiments.record_funnel_event(
                user_id,
                "promotion_entry_exposure",
                source=extra.get("source"),
                properties={
                    "surface": extra.get("source"),
                    "button_id": extra.get("button_id"),
                    "button_label": extra.get("button_label"),
                },
                request_id=request_id,
            )
        except Exception:
            logger.exception("failed to record promotion button exposure")
