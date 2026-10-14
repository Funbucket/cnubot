"""Structured notice cards and persistent per-user browsing snapshots."""
import hashlib
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any

from app.utils.benefits_data import KST, read_snapshot
from app.utils.kakao_json_response import KakaoJsonResponse as Response

logger = logging.getLogger(__name__)
CATEGORIES = {
    "장학금": "scholarship", "교육": "education", "해외교류": "international",
    "인턴창업": "internship", "교내채용": "recruitment", "학사정보": "academic", "행사": "event",
}
CHOICES = [("최신 공고", "학교혜택 최신"), ("마감임박", "학교혜택 마감임박")]
CHOICES += [(name, f"학교혜택 {name}") for name in CATEGORIES]
PAGE_SIZE = 5
STATE_TTL = timedelta(minutes=30)
CATEGORY_MENU_MESSAGE = "학교혜택 분야"
HOME_INTRO = (
    "백마광장·국제교류본부 소식을 모았어요 🎓\n"
    "원하는 정보는 ‘분야 더 보기’에서 골라보세요."
)


def now_kst() -> datetime:
    return datetime.now(KST)


def load_benefits() -> list[dict[str, Any]]:
    return read_snapshot().get("items", [])


def _status(item: dict, now: datetime | None = None) -> str:
    now = now or now_kst()
    if item.get("status") in {"closed", "cancelled"}:
        return item["status"]
    try:
        if item.get("deadline_at"):
            at = datetime.fromisoformat(item["deadline_at"])
            at = at.replace(tzinfo=KST) if at.tzinfo is None else at
            return "open" if at >= now else "closed"
        if item.get("deadline"):
            return "open" if datetime.fromisoformat(item["deadline"]).date() >= now.date() else "closed"
    except (TypeError, ValueError):
        pass
    return "unknown"


def selection(utterance: str) -> str:
    return utterance if utterance in {message for _, message in CHOICES} else "학교혜택 최신"


def consolidate(items: list[dict]) -> list[dict]:
    """Combine recent cross-board reposts with the same title and deadline."""
    groups: dict[tuple, list[dict]] = {}
    for item in items:
        title = re.sub(r"\s*\(\s*[~～].*$", "", item["title"])
        title = re.sub(r"\s*안내\s*$", "", title)
        title = re.sub(r"\s+", "", title)
        key = (title, item.get("deadline"))
        matched = None
        for existing in groups.get(key, []):
            try:
                days = abs((datetime.fromisoformat(item["published_at"]).date()
                            - datetime.fromisoformat(existing["published_at"]).date()).days)
            except (KeyError, ValueError):
                continue
            if (existing.get("source") != item.get("source") and days <= 7
                    and (not existing.get("deadline_at") or not item.get("deadline_at")
                         or existing["deadline_at"] == item["deadline_at"])):
                matched = existing
                break
        if matched is None:
            groups.setdefault(key, []).append(dict(item))
        else:
            categories = list(dict.fromkeys(matched["categories"] + item["categories"]))
            def quality(row):
                return (row.get("source") == "international", bool(row.get("deadline_at")),
                        bool(row.get("benefit")), bool(row.get("eligibility")), row["published_at"])
            if quality(item) > quality(matched):
                matched.clear()
                matched.update(item)
            matched["categories"] = categories
    return [item for group in groups.values() for item in group]


def _items(utterance: str, snapshot: dict | None = None) -> list[dict]:
    utterance = selection(utterance)
    items = consolidate((snapshot if snapshot is not None else read_snapshot()).get("items", []))
    now = now_kst()
    # Unknown application periods remain visible for 90 days, with clear labels.
    cutoff = (now.date() - timedelta(days=90)).isoformat()
    result = [item for item in items if _status(item, now) in {"open", "unknown"}
              and (_status(item, now) == "open" or item.get("published_at", "") >= cutoff)]
    if utterance == "학교혜택 마감임박":
        result = [item for item in result if _status(item, now) == "open"
                  and item.get("deadline", "") <= (now.date() + timedelta(days=7)).isoformat()]
        return sorted(result, key=lambda x: (x.get("deadline_at") or x["deadline"] + "T23:59:59+09:00", x["id"]))
    category = CATEGORIES.get(utterance.removeprefix("학교혜택 "))
    if category:
        result = [item for item in result if category in item.get("categories", [])]
    return sorted(result, key=lambda x: (x.get("published_time") or x.get("published_at", ""), x.get("id", "")), reverse=True)


def shorten(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit - 1].rstrip() + "…"


def deadline_label(item: dict) -> str:
    if not item.get("deadline"):
        return item.get("deadline_note") or "마감 미확인 · 원문/첨부 확인"
    try:
        if _status(item) == "closed":
            return "접수 마감 · 최신 공고 확인"
        end = datetime.fromisoformat(item["deadline"]).date()
        days = (end - now_kst().date()).days
        suffix = "오늘 마감" if days == 0 else f"D-{days}" if days > 0 else "마감"
        clock = ""
        if item.get("deadline_at"):
            at = datetime.fromisoformat(item["deadline_at"]).astimezone(KST)
            clock = " 24:00" if at.date() > end and at.hour == at.minute == 0 else " " + at.strftime("%H:%M")
        return f"{end:%m.%d}{clock} · {suffix}"
    except ValueError:
        return "마감 미확인 · 원문/첨부 확인"


def card(item: dict) -> dict:
    category = next((label for label, key in CATEGORIES.items() if key in item.get("categories", [])), "정보")
    information = (not item.get("deadline") and category in {"학사정보", "행사", "교육"}
                   and not re.search(r"모집|신청|접수|선발", item.get("title", "")))
    lines = ["📌 정보 안내 · 일정/조건은 원문 확인" if information else f"⏰ {deadline_label(item)}"]
    if item.get("benefit"):
        text = item["benefit"]
        amount = re.search(r"\d[\d,.]*\s*(?:%|만\s*원|원)|전액|무료", text)
        if amount and amount.start() > 20:
            scope = re.match(r"^(글로벌인재양성|자비\s*연수)", text)
            start = max(0, amount.start() - 13)
            start = text.rfind(" ", 0, start) + 1
            text = (scope[0] + ": " if scope else "") + text[start:]
        lines.append("혜택(일부): " + shorten(text, 32))
    elif item.get("summary"):
        lines.append("내용(요약): " + shorten(item["summary"], 32))
    if item.get("eligibility"):
        text = re.sub(r"^\s*[\d.\-]+\s*", "", item["eligibility"])
        text = re.sub(r"^(?:지원\s*(?:자격|대상)|신청\s*(?:자격|대상)|선발\s*대상|모집\s*대상)\s*[:：]?\s*", "", text)
        person = re.search(r"학부생|재학생|휴학생|대학생|대학원생", text)
        if person and person.start() > 20:
            scope = re.match(r"\([^)]{1,20}\)", text)
            text = (scope[0] + " " if scope else "") + text[person.start():person.end() + 20]
        text = re.sub(r"\(\s*", "(", text)
        text = re.sub(r"\s*\)", ")", text)
        lines.append("대상(일부): " + shorten(text, 26))
    if not item.get("benefit") and not item.get("summary") and not item.get("eligibility"):
        lines.append("상세 내용은 원문/첨부 확인" if information else "모집내용·지원대상은 원문/첨부 확인")
    lines.append(f"등록 {item.get('published_at', '')[5:].replace('-', '.')} · {shorten(item.get('source_name', '공식 공고'), 12)}")
    title = re.sub(r"\s*\(\s*[~～].*$", "", item.get("title", "학교혜택"))
    return {"title": shorten(f"[{category}] {title}", 50),
            # Kakao textCard carousels have a 128-character description limit.
            "description": shorten("\n".join(lines), 128),
            "buttons": [{"action": "webLink", "label": "공고 보기", "webLinkUrl": item["url"]}]}


def render(utterance: str, items: list[dict], page: int, snapshot: dict,
           can_page: bool = True, notice: str = "", show_intro: bool = False) -> dict:
    response = Response()
    page = max(0, min(page, max(0, (len(items) - 1) // PAGE_SIZE)))
    start = page * PAGE_SIZE
    selected = items[start:start + PAGE_SIZE]
    heading = utterance.removeprefix("학교혜택 ")
    if heading == "최신":
        heading = "최신 공고"
    if selected:
        total_pages = (len(items) + PAGE_SIZE - 1) // PAGE_SIZE
        if total_pages > 1:
            heading += f" · {page + 1} / {total_pages}페이지"
        else:
            heading += f" · 공고 {len(items)}건"
    else:
        heading += " · 7일 내 마감 공고가 없어요." if utterance == "학교혜택 마감임박" else " · 표시할 공고가 없어요."
    sources = snapshot.get("sources", {})
    category = CATEGORIES.get(utterance.removeprefix("학교혜택 "))
    relevant = [sources[category]] if category in sources else list(sources.values())
    stamps = [s.get("last_success_at") for s in relevant if s.get("last_success_at")]
    stamp = min(stamps) if stamps else snapshot.get("fetched_at") if not relevant else None
    delayed = False
    if stamp:
        try:
            collected = datetime.fromisoformat(stamp).astimezone(KST)
            if now_kst() - collected > timedelta(hours=24):
                delayed = True
                heading += f"\n갱신 지연 · {collected:%m.%d} 기준, 원문 확인"
        except ValueError:
            pass
    if not delayed and any(s.get("status") != "ok" or s.get("detail_failures") for s in relevant):
        heading += "\n일부 소식 갱신 중 · 원문 확인"
    if not snapshot:
        heading = "공고를 준비 중이에요. 잠시 후 다시 확인해주세요."
    if notice:
        heading += "\n" + notice
    if show_intro:
        heading = HOME_INTRO + "\n\n" + heading
    response.add_output_to_response(Response.create_simple_text(heading))
    if selected:
        response.add_output_to_response(Response.create_carousel([card(item) for item in selected], "textCard"))
    elif category and sources.get(category, {}).get("url"):
        response.add_output_to_response({"textCard": {
            "title": "공식 게시판도 확인해보세요",
            "description": "첨부에만 있는 신청 조건과 새로운 공고는 공식 게시판에서 확인할 수 있어요.",
            "buttons": [{"action": "webLink", "label": "공식 게시판", "webLinkUrl": sources[category]["url"]}],
        }})
    # Show useful entry shortcuts; keep subsequent browsing focused on paging.
    if show_intro:
        replies = [("마감임박", "학교혜택 마감임박"), ("분야 더 보기", CATEGORY_MENU_MESSAGE)]
    else:
        replies = [("마감임박", "학교혜택 마감임박")] if utterance == "학교혜택 최신" else [("최신 공고", "학교혜택 최신")]
        replies.append(("분야 더 보기", CATEGORY_MENU_MESSAGE))
    paging = []
    if can_page and page > 0 and not show_intro:
        paging.append(("◀️", "학교혜택 이전"))
    if can_page and start + PAGE_SIZE < len(items):
        paging.append(("▶️", "학교혜택 다음"))
    replies = replies + paging if show_intro else paging + replies
    response.add_quick_replies([Response.create_quick_reply(label, message) for label, message in replies])
    return response.get_response()


def category_menu_response() -> dict:
    response = Response()
    cards = []
    groups = [
        ("혜택·배움", "장학금, 해외 파견 모집, 교육 프로그램을 찾아보세요.", ["장학금", "해외교류", "교육"]),
        ("진로·채용", "사업단 창업·교육 공고와 교내 채용을 확인하세요.", ["인턴창업", "교내채용"]),
        ("학교 소식", "학사 안내와 교내 행사·세미나를 살펴보세요.", ["학사정보", "행사"]),
    ]
    for title, description, names in groups:
        buttons = [{"action": "message", "label": "인턴·창업" if name == "인턴창업" else name,
                    "messageText": f"학교혜택 {name}"} for name in names]
        cards.append({
            "title": title, "description": description, "buttons": buttons,
        })
    response.add_output_to_response(Response.create_carousel(cards, "textCard"))
    response.add_quick_replies([
        Response.create_quick_reply("최신 공고", "학교혜택 최신"),
        Response.create_quick_reply("마감임박", "학교혜택 마감임박"),
    ])
    return response.get_response()


def list_response(utterance: str, page: int = 0) -> dict:
    if utterance == CATEGORY_MENU_MESSAGE:
        return category_menu_response()
    snapshot = read_snapshot()
    return render(selection(utterance), _items(utterance, snapshot), page, snapshot, can_page=False)


def transition(state: dict | None, utterance: str, snapshot: dict, now: datetime) -> tuple[dict, str]:
    """A list snapshot prevents a batch refresh from reordering the user's pages."""
    paging = utterance in {"학교혜택 다음", "학교혜택 이전"}
    try:
        valid = bool(state) and datetime.fromisoformat(state["expires_at"]) > now
    except (KeyError, TypeError, ValueError):
        valid = False
    notice = ""
    if not paging or not valid:
        chosen = selection(utterance)
        state = {"selection": chosen, "items": _items(chosen, snapshot), "page": 0,
                 "snapshot": {k: snapshot[k] for k in ("fetched_at", "sources") if k in snapshot},
                 "expires_at": (now + STATE_TTL).isoformat()}
        if paging:
            notice = "이전 목록이 만료되어 최신 공고부터 보여드려요. 분야를 다시 선택할 수 있어요."
    else:
        state = dict(state)
        last = max(0, (len(state["items"]) - 1) // PAGE_SIZE)
        state["page"] = min(last, state["page"] + 1) if utterance == "학교혜택 다음" else max(0, state["page"] - 1)
    return state, notice


async def browse_response(utterance: str, user_id: str | None, *, show_intro: bool = False) -> dict:
    if utterance == CATEGORY_MENU_MESSAGE:
        # Opening the menu preserves the user's current list and page.
        return category_menu_response()
    snapshot = read_snapshot()
    if not user_id:
        return render(selection(utterance), _items(utterance, snapshot), 0, snapshot, can_page=False,
                      notice="분야 버튼으로 원하는 정보를 골라주세요.", show_intro=show_intro)
    user_hash = hashlib.sha256(user_id.encode()).hexdigest()
    try:
        from app.database import get_pool
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", "benefits:" + user_hash)
                await conn.execute("""WITH expired AS (
                    SELECT user_hash FROM benefits_browse_states WHERE expires_at <= NOW()
                    ORDER BY expires_at LIMIT 100 FOR UPDATE SKIP LOCKED
                ) DELETE FROM benefits_browse_states USING expired
                  WHERE benefits_browse_states.user_hash = expired.user_hash""")
                record = await conn.fetchrow("SELECT state FROM benefits_browse_states WHERE user_hash = $1", user_hash)
                state = record["state"] if record else None
                if isinstance(state, str):
                    state = json.loads(state)
                state, notice = transition(state, utterance, snapshot, now_kst())
                await conn.execute(
                    """INSERT INTO benefits_browse_states (user_hash, state, expires_at)
                       VALUES ($1, $2::jsonb, $3)
                       ON CONFLICT (user_hash) DO UPDATE SET state = EXCLUDED.state, expires_at = EXCLUDED.expires_at""",
                    user_hash, json.dumps(state, ensure_ascii=False), datetime.fromisoformat(state["expires_at"]))
        return render(state["selection"], state["items"], state["page"], state["snapshot"], notice=notice,
                      show_intro=show_intro)
    except Exception:
        # Never expose user IDs, database URLs or exception details in logs.
        logger.warning("Notice browsing state unavailable")
        return render(selection(utterance), _items(utterance, snapshot), 0, snapshot, can_page=False,
                      notice="목록 이동을 잠시 사용할 수 없어요. 분야별 첫 공고와 원문은 확인할 수 있어요.",
                      show_intro=show_intro)


def detail_response(utterance: str, recent: list[dict] | None = None) -> dict:
    # Legacy endpoint only; all new cards open the original notice directly.
    match = re.search(r"(\d+)번", utterance)
    index = int(match[1]) - 1 if match else -1
    items = recent if recent is not None else _items("학교혜택 최신")
    response = Response()
    if 0 <= index < len(items):
        response.add_output_to_response({"textCard": card(items[index])})
    else:
        response.add_output_to_response(Response.create_simple_text("공고를 찾지 못했어요. 최신 공고을 다시 선택해주세요."))
    response.add_quick_replies([Response.create_quick_reply("최신 공고", "학교혜택 최신")])
    return response.get_response()
