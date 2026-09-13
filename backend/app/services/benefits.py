"""학교혜택 공고 조회와 카카오 응답 생성."""
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.utils import kakao_json_response

DATA_PATH = Path("app/static/data/benefits.json")
CATEGORIES = {
    "장학금": "scholarship",
    "교육": "education",
    "해외교류": "international",
    "인턴창업": "internship",
    "교내채용": "recruitment",
}


def load_benefits() -> list[dict[str, Any]]:
    try:
        payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else payload.get("items", [])


def _status(item: dict[str, Any]) -> str:
    if item.get("status") in {"closed", "cancelled"}:
        return item["status"]
    deadline = item.get("deadline")
    if not deadline:
        return "unknown"
    try:
        return "open" if date.fromisoformat(deadline) >= date.today() else "closed"
    except ValueError:
        return "unknown"


def _items(utterance: str) -> list[dict[str, Any]]:
    items = load_benefits()
    if "마감임박" in utterance:
        today = date.today()
        result = []
        for item in items:
            try:
                days = (date.fromisoformat(item["deadline"]) - today).days
            except (KeyError, ValueError):
                continue
            if 0 <= days <= 7 and _status(item) == "open":
                result.append(item)
        return sorted(result, key=lambda x: x.get("deadline", ""))
    category = next((value for key, value in CATEGORIES.items() if key in utterance), None)
    # 상세 첨부 해석 전에도 새 공고를 숨기지 않는다. 마감일 미확인은
    # 목록에 노출하되 마감임박 계산에서는 제외한다.
    result = [item for item in items if _status(item) in {"open", "unknown"}]
    if category:
        result = [item for item in result if category in item.get("categories", [])]
    query = utterance.split("검색", 1)[1].strip() if "검색" in utterance else ""
    if query:
        result = [item for item in result if query.lower() in json.dumps(item, ensure_ascii=False).lower()]
    return sorted(result, key=lambda x: (x.get("published_at", ""), x.get("id", "")), reverse=True)


def _buttons(item: dict[str, Any], index: int) -> list[dict[str, str]]:
    # 목록에서 상세 메시지를 거치지 않고 공식 원문으로 바로 이동한다.
    return [{"action": "webLink", "label": "자세히 보기", "webLinkUrl": item.get("url", "https://plus.cnu.ac.kr/")}]


def list_response(utterance: str, page: int = 0) -> dict:
    items = _items(utterance)
    start = page * 5
    selected = items[start:start + 5]
    response = kakao_json_response.KakaoJsonResponse()
    if not selected:
        response.add_output_to_response(kakao_json_response.KakaoJsonResponse.create_simple_text("현재 확인된 학교혜택이 없어요."))
    else:
        cards = []
        for index, item in enumerate(selected, 1):
            deadline = item.get("deadline") or "마감일 확인 필요"
            benefit = item.get("benefit") or "혜택 내용은 공고에서 확인"
            eligibility = item.get("eligibility") or "지원 대상은 공고에서 확인"
            cards.append({"title": item.get("title", "학교혜택"), "description": f"{benefit}\n대상: {eligibility}\n마감: {deadline}", "buttons": _buttons(item, index)})
        response.add_output_to_response(kakao_json_response.KakaoJsonResponse.create_carousel(cards, "textCard"))
    replies = [("최신", "학교혜택 최신"), ("마감임박", "학교혜택 마감임박"), ("장학금", "학교혜택 장학금"), ("교육", "학교혜택 교육")]
    if start + 5 < len(items):
        replies.append(("다음 5개", "학교혜택 다음"))
    response.add_quick_replies([kakao_json_response.KakaoJsonResponse.create_quick_reply(label, message) for label, message in replies])
    return response.get_response()


def detail_response(utterance: str, recent: list[dict[str, Any]] | None = None) -> dict:
    match = re.search(r"(\d+)번", utterance)
    index = int(match.group(1)) - 1 if match else -1
    items = recent or _items("학교혜택 최신")
    item = items[index] if 0 <= index < len(items) else None
    response = kakao_json_response.KakaoJsonResponse()
    if not item:
        response.add_output_to_response(kakao_json_response.KakaoJsonResponse.create_simple_text("공고 번호를 찾지 못했어요. 학교혜택 최신을 먼저 확인해주세요."))
        return response.get_response()
    detail = f"혜택: {item.get('benefit', '공고 내용 확인')}\n대상: {item.get('eligibility', '지원 대상 확인 필요')}\n마감: {item.get('deadline', '확인 필요')}\n신청: {item.get('apply_method', '공식 공고 확인')}"
    buttons = [{"action": "webLink", "label": "공식 공고", "webLinkUrl": item.get("url", "https://plus.cnu.ac.kr/")}]
    response.add_output_to_response({"textCard": kakao_json_response.KakaoJsonResponse.create_text_card(item.get("title", "학교혜택"), detail, buttons)})
    response.add_quick_replies([kakao_json_response.KakaoJsonResponse.create_quick_reply("목록", "학교혜택 목록")])
    return response.get_response()
