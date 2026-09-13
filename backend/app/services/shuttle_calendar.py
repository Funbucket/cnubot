"""Calendar rules for shuttle service dates, independent of Kakao rendering."""
from datetime import date, timedelta


def _event_date(value: str) -> date:
    return date.fromisoformat(value)


def _calendar_event_on(calendar: dict, target: date) -> list[dict]:
    return [
        event
        for event in calendar.get("events", [])
        if _event_date(event["start"]) <= target <= _event_date(event["end"])
    ]


def _is_holiday(event: dict) -> bool:
    title = event.get("title", "")
    return any(
        keyword in title
        for keyword in (
            "공휴일",
            "대체공휴일",
            "개교기념일",
            "선거일",
            "설날",
            "추석",
            "어린이날",
            "현충일",
            "광복절",
            "한글날",
            "개천절",
            "부처님오신날",
            "기독탄신일",
            "삼일절",
            "신정",
        )
    )


def _is_break(calendar: dict, target: date) -> bool:
    phase_events = [
        event
        for event in calendar.get("events", [])
        if "방학" in event.get("title", "") or "개강일" in event.get("title", "")
    ]
    phase_events.sort(key=lambda event: _event_date(event["start"]))
    first_term_start = next(
        (
            _event_date(event["start"])
            for event in phase_events
            if "제1학기 개강일" in event.get("title", "")
        ),
        None,
    )
    if first_term_start and target < first_term_start:
        return True
    latest = next(
        (event for event in reversed(phase_events) if _event_date(event["start"]) <= target),
        None,
    )
    return bool(latest and "방학" in latest.get("title", ""))


def _next_service_date(calendar: dict, target: date) -> date:
    candidate = target + timedelta(days=1)
    for _ in range(370):
        if (
            candidate.weekday() < 5
            and not _is_break(calendar, candidate)
            and not any(_is_holiday(event) for event in _calendar_event_on(calendar, candidate))
        ):
            return candidate
        candidate += timedelta(days=1)
    return target + timedelta(days=1)


def _non_operation_reason(calendar: dict, target: date) -> str | None:
    if target.weekday() >= 5:
        return "주말"
    events = _calendar_event_on(calendar, target)
    holiday = next((event for event in events if _is_holiday(event)), None)
    if holiday:
        return holiday["title"]
    if _is_break(calendar, target):
        return "방학"
    return None
