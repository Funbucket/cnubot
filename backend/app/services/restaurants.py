"""Kakao restaurant browsing with verified meals and serialized per-user state."""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlencode, urlsplit

from app.services import restaurant_catalog as catalog_store
from app.utils.kakao_json_response import KakaoJsonResponse as Response

logger = logging.getLogger(__name__)
HOME = "학교 주변 맛집"
RANDOM = "주변맛집 랜덤"
MORE = "주변맛집 다른곳"
RATING_MENU = "주변맛집 별점"
AREAS = {"주변맛집 궁동": "궁동", "주변맛집 어은동": "어은동", "주변맛집 죽동": "죽동"}
BUDGETS = {
    "1만원 미만": ("🪙 1만원 미만", 0, 10000),
    "1만원대": ("🍚 1만원대", 10000, 20000),
    "2만원 이상": ("🍽️ 2만원 이상", 20000, None),
}
# Every area/budget combination is finite and explicitly registered with Kakao.
MEAL_CHOICES = {f"주변맛집 {area} {budget}": (area, budget)
                for area in AREAS.values() for budget in BUDGETS}
RATINGS = {"주변맛집 별점 전체": 0.0, "주변맛집 별점 3.5 이상": 3.5,
           "주변맛집 별점 4.0 이상": 4.0, "주변맛집 별점 4.5 이상": 4.5}
ROUTE_MESSAGES = {"home": {HOME}, "random": {RANDOM}, "area": set(AREAS), "budget": set(MEAL_CHOICES),
                  "rating": {RATING_MENU, *RATINGS}, "more": {MORE}}
STATE_TTL = timedelta(minutes=30)
HISTORY_TTL = timedelta(days=7)
MIN_SCORE = 3.0
MIN_REVIEWS = 10


def reply(label, text):
    return Response.create_quick_reply(label, text)


def entry_reply():
    return reply("🍽️ 학교 주변 맛집", HOME)


def home_response(notice=""):
    response = Response().add_output_to_response(Response.create_simple_text(
        (notice + "\n" if notice else "") + "🍽️ 학교 주변 맛집\n⭐ 3.0 이상 · 평가 10개 이상\n어디서 먹을까요?"))
    response.add_quick_replies([reply("🎲 바로 추천", RANDOM)]
                               + [reply("📍 " + area, message) for message, area in AREAS.items()])
    return response.get_response()


def budget_response(area, notice=""):
    response = Response().add_output_to_response(Response.create_simple_text(
        (notice + "\n" if notice else "") + f"📍 {area}\n한 끼 예산은 얼마인가요?"))
    response.add_quick_replies([reply(values[0], f"주변맛집 {area} {budget}")
                              for budget, values in BUDGETS.items()] + [reply("지역 변경", HOME)])
    return response.get_response()


def _time(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo and parsed.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def prepare_state(previous, now):
    previous = previous if isinstance(previous, dict) else {}
    history = previous.get("history", {})
    history = {key: value for key, value in history.items()
               if isinstance(key, str) and (stamp := _time(value))
               and timedelta(0) <= now - stamp <= HISTORY_TTL} if isinstance(history, dict) else {}
    expiry = _time(previous.get("expires_at"))
    valid = bool(expiry and expiry > now and previous.get("mode") in (None, "random")
                 and previous.get("area") in (None, *AREAS.values())
                 and previous.get("budget") in (None, *BUDGETS)
                 and previous.get("min_rating") in tuple(RATINGS.values())
                 and isinstance(previous.get("seen"), list)
                 and all(isinstance(key, str) for key in previous["seen"])
                 and isinstance(previous.get("session_id"), str))
    if valid:
        state = dict(previous)
        state["seen"] = list(previous["seen"])
    else:
        state = {"mode": None, "area": None, "budget": None, "min_rating": 0.0, "seen": [],
                 "session_id": uuid.uuid4().hex}
    state["history"] = history
    state["expires_at"] = (now + STATE_TTL).isoformat()
    return state, valid


def candidates(catalog, state, now):
    if not state.get("area") or state.get("budget") not in BUDGETS:
        return []
    _, low, high = BUDGETS[state["budget"]]
    minimum = state.get("min_rating", 0)
    result = []
    for item in catalog.items:
        if not item.enabled or item.area != state["area"]:
            continue
        rating = qualifying_rating(catalog, item, now)
        if not rating:
            continue
        if minimum and (not catalog.ratings_enabled or not catalog.rating_usage_basis
                        or rating.score < minimum):
            continue
        meals = [meal for meal in catalog_store.fresh_meals(item, now)
                 if meal.per_person >= low and (high is None or meal.per_person < high)]
        if meals:
            result.append((item, min(meals, key=lambda meal: (meal.per_person, meal.name))))
    return result


def qualifying_rating(catalog, item, now):
    if not catalog.ratings_enabled or not catalog.rating_usage_basis:
        return None
    rating = catalog_store.fresh_rating(item, now)
    return rating if rating and rating.score >= MIN_SCORE and rating.count >= MIN_REVIEWS else None


def random_candidates(catalog, now):
    result = []
    for item in catalog.items:
        if not item.enabled or not qualifying_rating(catalog, item, now):
            continue
        meals = [meal for meal in catalog_store.fresh_meals(item, now) if meal.per_person < 20000]
        if meals:
            result.append((item, min(meals, key=lambda meal: (meal.per_person, meal.name))))
    return result


def choose(rows, state, user_hash, now, *, limit=3, randomize=False):
    seen = set(state["seen"])
    available = [row for row in rows if row[0].id not in seen]
    restarted = bool(rows and not available)
    if restarted:
        available = rows
        state["seen"] = []
    history = state["history"]
    salt = user_hash + now.date().isoformat()
    floor = now - HISTORY_TTL - timedelta(seconds=1)
    available.sort(key=lambda row: (
        row[0].id in history,
        _time(history.get(row[0].id)) or floor,
        secrets.randbits(64) if randomize else hashlib.sha256((salt + row[0].id).encode()).hexdigest(),
    ))
    selected, cuisines = [], set()
    # Novelty takes precedence over cuisine variety, including across new sessions.
    for tier in ([row for row in available if row[0].id not in history],
                 [row for row in available if row[0].id in history]):
        for row in tier:
            if len(selected) == limit:
                break
            if row[0].cuisine not in cuisines:
                selected.append(row)
                cuisines.add(row[0].cuisine)
        for row in tier:
            if len(selected) == limit:
                break
            if row not in selected:
                selected.append(row)
    for item, _ in selected:
        state["seen"].append(item.id)
        history[item.id] = now.isoformat()
    state["history"] = dict(sorted(history.items(), reverse=True, key=lambda pair: pair[1])[:200])
    exhausted = bool(rows and all(row[0].id in state["seen"] for row in rows))
    return selected, exhausted, restarted


def _secret():
    return os.getenv("RESTAURANTS_TRACKING_SECRET") or os.getenv("PROMOTION_TRACKING_SECRET", "")


def _base_url():
    value = os.getenv("SERVER_URL", "").rstrip("/")
    parsed = urlsplit(value)
    return value if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password else ""


def map_link(item, state, user_hash, now):
    if not (_secret() and _base_url() and user_hash):
        return item.place_url
    payload = {"place_id": item.id, "user_hash": user_hash, "session_id": state["session_id"],
               "area": item.area if state.get("mode") == "random" else state["area"],
               "budget": state["budget"], "min_rating": state["min_rating"], "mode": state.get("mode"),
               "exposed_at": now.isoformat(), "expires": int((now + HISTORY_TTL).timestamp()),
               "click_id": uuid.uuid4().hex}
    encoded = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(_secret().encode(), ("restaurants:" + encoded).encode(), hashlib.sha256).hexdigest()
    return _base_url() + "/restaurants/map?" + urlencode({"token": encoded + "." + signature})


def read_map_token(token, now):
    try:
        if not _secret() or len(token) > 3000:
            return None
        encoded, signature = token.split(".", 1)
        expected = hmac.new(_secret().encode(), ("restaurants:" + encoded).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        if (not isinstance(payload, dict) or not isinstance(payload.get("expires"), int)
                or payload["expires"] <= now.timestamp()
                or not all(isinstance(payload.get(key), str) for key in
                           ("place_id", "user_hash", "session_id", "click_id"))
                or not _time(payload.get("exposed_at"))):
            return None
        return payload
    except (ValueError, TypeError, UnicodeError):
        return None


def _short(value, limit):
    return value if len(value) <= limit else value[:limit - 1] + "…"


def card(item, meal, catalog, state, user_hash, now):
    meal_name = _short(meal.name, 24)
    if meal.diners == 1:
        price = f"{meal_name} · {meal.total_price:,}원"
    else:
        approx = "약 " if meal.total_price % meal.diners else ""
        price = f"{meal_name} · {meal.diners}인 {meal.total_price:,}원\n1인 {approx}{meal.per_person:,}원"
    rating = catalog_store.fresh_rating(item, now) if catalog.ratings_enabled and catalog.rating_usage_basis else None
    lines = [price]
    if rating:
        lines.append(f"⭐ {rating.score:.1f} · 리뷰 {rating.count:,}개")
    if item.origin == "manual" and item.reason:
        lines.append(item.reason)
    if (item.origin == "kakao_public" and meal.source_updated_on
            and (now.date() - meal.source_updated_on).days > 180):
        lines.append("가격은 방문 전 확인해 주세요.")
    # Provenance and collection times remain in the catalog, outside the card.
    description = "\n".join(lines)
    return Response.create_text_card(_short(f"{item.name} · {item.cuisine}", 50), description,
        [{"action": "webLink", "label": "메뉴·후기 보기", "webLinkUrl": map_link(item, state, user_hash, now)}])


def condition_label(state):
    label = f"{state['area']} · {state['budget']}"
    if state["min_rating"]:
        label += f" · ⭐ {state['min_rating']:.1f} 이상"
    return label


def render(catalog, state, selected, exhausted, restarted, user_hash, now, *, can_browse, notice=""):
    text = "📍 " + condition_label(state)
    if notice:
        text += "\n" + notice
    if selected:
        text += ("\n예산에 맞춰 골라봤어요 🍽️" if len(selected) == 3
                 else f"\n이번엔 이 {len(selected)}곳 어때요? 🍽️")
        if any(item.origin == "kakao_public" for item, _ in selected):
            text += "\n가격은 카카오맵 등록 기준이에요."
        else:
            text += "\n메뉴와 가격은 카드에서 확인하세요."
        if restarted:
            text += "\n봤던 곳도 다시 골라봤어요."
        elif exhausted:
            text += "\n이 조건의 맛집을 모두 봤어요."
    elif not catalog.items:
        text += "\n아직 소개할 맛집이 없어요. 잠시 후 다시 찾아주세요."
    else:
        text += ("\n선택한 조건의 맛집이 없어요. 별점 기준을 바꾸거나 다시 골라보세요."
                 if state["min_rating"] else "\n이 조건에 맞는 식당을 찾지 못했어요. 지역이나 예산을 바꿔보세요.")
    response = Response().add_output_to_response(Response.create_simple_text(text))
    if selected:
        response.add_output_to_response(Response.create_carousel([
            card(item, meal, catalog, state, user_hash if can_browse else "", now) for item, meal in selected]))
    replies = []
    if can_browse:
        if selected:
            replies.append(reply("🔄 다시 둘러보기" if exhausted else "🔄 다른 곳", MORE))
        if catalog_store.ratings_available(catalog, now):
            replies.append(reply("⭐ 별점 조건", RATING_MENU))
        elif state["min_rating"]:
            replies.append(reply("별점 전체", "주변맛집 별점 전체"))
    replies.append(reply("⚙️ 조건 변경", HOME))
    response.add_quick_replies(replies)
    return response.get_response()


def render_random(catalog, state, selected, restarted, user_hash, now, *, can_browse):
    if selected:
        item, meal = selected[0]
        text = f"🎲 오늘은 여기 어때요?\n📍 {item.area} · 2만원 미만"
        text += ("\n가격은 카카오맵 등록 기준이에요." if item.origin == "kakao_public"
                 else "\n메뉴와 가격은 카드에서 확인하세요.")
        if restarted:
            text += "\n봤던 곳도 다시 골라봤어요."
    else:
        text = "🎲 지금 추천할 식당이 없어요.\n지역과 예산을 골라볼까요?"
    response = Response().add_output_to_response(Response.create_simple_text(text))
    if selected:
        response.add_output_to_response(Response.create_carousel([
            card(item, meal, catalog, state, user_hash if can_browse else "", now)]))
    replies = [reply("🔄 다시 뽑기", RANDOM)] if selected and can_browse else []
    replies.append(reply("⚙️ 조건 고르기", HOME))
    response.add_quick_replies(replies)
    return response.get_response()


def transition(previous, utterance, catalog, user_hash, now, *, can_browse=True):
    state, valid = prepare_state(previous, now)
    if utterance == HOME:
        state.update(mode=None, area=None, budget=None, min_rating=0.0, seen=[], session_id=uuid.uuid4().hex)
        return state, home_response(), None
    if utterance == RANDOM:
        refresh = valid and state.get("mode") == "random"
        if not refresh:
            state.update(mode="random", area=None, budget=None, min_rating=0.0, seen=[])
        selected, _, restarted = choose(random_candidates(catalog, now), state, user_hash, now,
                                        limit=1, randomize=True)
        response = render_random(catalog, state, selected, restarted, user_hash, now, can_browse=can_browse)
        event = {"mode": "random", "area": selected[0][0].area if selected else None,
                 "budget": "2만원 미만", "min_rating": 0.0,
                 "place_ids": [item.id for item, _ in selected], "count": len(selected),
                 "revision": catalog.revision, "refresh": refresh}
        return state, response, event
    if utterance in AREAS:
        state.update(mode=None, area=AREAS[utterance], budget=None, min_rating=0.0, seen=[])
        return state, budget_response(state["area"]), None
    if utterance in MEAL_CHOICES:
        area, budget = MEAL_CHOICES[utterance]
        state.update(mode=None, area=area, budget=budget, min_rating=0.0, seen=[])
    elif utterance in {MORE, RATING_MENU, *RATINGS}:
        if not can_browse or not valid or not state["area"] or not state["budget"]:
            notice = "다시 찾아볼까요? 지역부터 골라주세요."
            return state, home_response(notice), None
        available = catalog_store.ratings_available(catalog, now)
        if utterance == RATING_MENU:
            if not available:
                response = Response().add_output_to_response(Response.create_simple_text(
                    "지금은 별점으로 고르기 어려워요. 지역과 예산으로 찾아보세요."))
                response.add_quick_replies([reply("별점 전체", "주변맛집 별점 전체"), reply("조건 변경", HOME)])
            else:
                response = Response().add_output_to_response(Response.create_simple_text(
                    "📍 " + condition_label(state) + "\n몇 점 이상으로 볼까요?\n카카오맵 별점 기준이에요."))
                response.add_quick_replies([reply("전체" if not value else f"⭐ {value:.1f} 이상", message)
                                           for message, value in RATINGS.items()])
            return state, response.get_response(), None
        if utterance in RATINGS:
            minimum = RATINGS[utterance]
            if minimum and not available:
                response = Response().add_output_to_response(Response.create_simple_text(
                    "지금은 이 별점 조건으로 찾을 수 없어요. 별점 전체로 다시 볼까요?"))
                response.add_quick_replies([reply("별점 전체", "주변맛집 별점 전체"), reply("조건 변경", HOME)])
                return state, response.get_response(), None
            if minimum != state["min_rating"]:
                state.update(min_rating=minimum, seen=[])
    else:
        return state, home_response("지역부터 골라주세요."), None
    selected, exhausted, restarted = choose(candidates(catalog, state, now), state, user_hash, now)
    response = render(catalog, state, selected, exhausted, restarted, user_hash, now, can_browse=can_browse)
    event = {"area": state["area"], "budget": state["budget"], "min_rating": state["min_rating"],
             "place_ids": [item.id for item, _ in selected], "count": len(selected), "revision": catalog.revision,
             "refresh": utterance == MORE}
    return state, response, event


async def record_event(conn, event_name, user_hash, session_id, properties, event_id=None):
    await conn.execute("""INSERT INTO restaurant_events
        (event_id, event_name, user_hash, session_id, properties)
        VALUES ($1, $2, $3, $4, $5::jsonb) ON CONFLICT (event_id) DO NOTHING""",
        event_id or uuid.uuid4().hex, event_name, user_hash, session_id,
        json.dumps(properties, ensure_ascii=False))


async def browse_response(utterance, user_id):
    import asyncio
    catalog = await asyncio.to_thread(catalog_store.safe_catalog)
    now = catalog_store.now_kst()
    if not user_id:
        return transition(None, utterance, catalog, "", now, can_browse=False)[1]
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    try:
        from app.database import get_pool
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", "restaurants:" + user_hash)
                await conn.execute("""WITH expired AS (
                    SELECT user_hash FROM restaurant_browse_states WHERE updated_at < NOW() - INTERVAL '7 days'
                    LIMIT 100 FOR UPDATE SKIP LOCKED
                ) DELETE FROM restaurant_browse_states USING expired
                  WHERE restaurant_browse_states.user_hash = expired.user_hash""")
                row = await conn.fetchrow("SELECT state FROM restaurant_browse_states WHERE user_hash = $1", user_hash)
                previous = row["state"] if row else None
                if isinstance(previous, str):
                    previous = json.loads(previous)
                state, response, event = transition(previous, utterance, catalog, user_hash, now)
                await conn.execute("""INSERT INTO restaurant_browse_states (user_hash, state, updated_at)
                    VALUES ($1, $2::jsonb, NOW()) ON CONFLICT (user_hash)
                    DO UPDATE SET state = EXCLUDED.state, updated_at = NOW()""",
                    user_hash, json.dumps(state, ensure_ascii=False))
                # Analytics failure must not roll back a working browsing session.
                try:
                    async with conn.transaction():
                        if utterance == HOME:
                            await record_event(conn, "entry", user_hash, state["session_id"], {})
                        if event is not None:
                            await record_event(conn, "recommendation", user_hash, state["session_id"], event)
                except Exception:
                    logger.warning("Restaurant analytics unavailable")
        return response
    except Exception:
        logger.warning("Restaurant browsing state unavailable")
        # Area-qualified budget buttons keep basic browsing usable without a database.
        return transition(None, utterance, catalog, "", now, can_browse=False)[1]
