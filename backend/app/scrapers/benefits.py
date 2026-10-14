"""Collect official notices and explicitly labelled application deadlines."""
import hashlib
import json
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from app.utils.benefits_data import KST, SEED_PATH, data_path, read_snapshot

SOURCES = {
    "scholarship": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0713&menu_dvs_cd=0713&site_dvs_cd=kr",
    "education": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0704&menu_dvs_cd=0704&site_dvs_cd=kr",
    "internship": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0709&menu_dvs_cd=0709&site_dvs_cd=kr",
    "recruitment": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0705&menu_dvs_cd=0705&site_dvs_cd=kr",
    "international": "https://cnuint.cnu.ac.kr/cnuint/notice/recruit.do",
    "academic": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0702&menu_dvs_cd=0702&site_dvs_cd=kr",
    "event": "https://plus.cnu.ac.kr/_prog/_board/?code=sub010714&menu_dvs_cd=0712&site_dvs_cd=kr",
}
SOURCE_NAMES = {
    "scholarship": "장학게시판", "education": "교육정보", "internship": "사업단 창업·교육",
    "recruitment": "채용·초빙", "international": "국제교류본부", "academic": "학사정보", "event": "세미나·행사",
}
DATE_RE = re.compile(
    r"(?<![\d.])(?:(?P<year>20\d{2}|\d{2})\s*[.년/\-]\s*)?"
    r"(?P<month>\d{1,2})\s*[.월/\-]\s*(?P<day>\d{1,2})(?!\d)"
)
DEADLINE_LABEL = re.compile(
    r"(?:(?:신청|접수|모집|지원서|신청서|서류\s*제출|제출|등록)\s*"
    r"(?:작성\s*|제출\s*)?(?:기간|기한|마감)|마감\s*(?:일|시각))"
)
RESULT_TITLE = re.compile(r"합격자|선발자|선발\s*결과|서류\s*심사\s*결과|결과\s*발표|최종\s*합격|장학생\s*선정|(?:모집|채용|행사)\s*취소")


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def public_excerpt(text: str) -> str:
    # Keep source contact details, account names and addresses out of snapshots.
    return re.split(
        r"문의(?:처)?|담당자|연락처|이메일|전화|주소|https?://|[\w.+-]+@[\w.-]+|0\d{1,2}[-\s]\d{3,4}[-\s]\d{4}",
        text)[0].strip()


def clock_at(day: date, tail: str) -> str | None:
    clock = re.match(
        r"\s*[.일]?\s*(?:\([^)]{1,10}\)\s*)?(?:(오전|오후)\s*)?"
        r"(\d{1,2})(?::(\d{2})|시(?:\s*(\d{1,2})\s*분)?)", tail)
    if not clock:
        return None
    hour, minute = int(clock[2]), int(clock[3] or clock[4] or 0)
    if clock[1]:
        if 13 <= hour <= 23 and clock[1] == "오후":
            pass  # Some official notices redundantly write '오후 23시 59분'.
        elif not 1 <= hour <= 12:
            return None
        else:
            hour = hour % 12 + (12 if clock[1] == "오후" else 0)
    if hour == 24 and minute == 0:
        return (datetime(day.year, day.month, day.day, tzinfo=KST) + timedelta(days=1)).isoformat()
    if hour >= 24 or minute >= 60:
        return None
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=KST).isoformat()


def dates_in(text: str, reference: date) -> list[tuple[date, str | None]]:
    found = []
    year, previous, previous_end = reference.year, None, 0
    for match in DATE_RE.finditer(text):
        if (not match.group("year") and "/" in match.group(0)
                and re.search(r"수업일수\s*$", text[max(0, match.start() - 20):match.start()])):
            continue
        tail = text[match.end():]
        if re.match(r"[가-힣A-Za-z]", tail) and not tail.startswith("일"):
            continue  # Fractions like '수업일수 1/3선' are not dates.
        explicit = match.group("year")
        month, day = int(match.group("month")), int(match.group("day"))
        if explicit:
            year = int(explicit) + (2000 if len(explicit) == 2 else 0)
        elif previous and month < previous.month and re.search(r"[~～]", text[previous_end:match.start()]):
            year += 1
        elif not previous and reference.month == 12 and month == 1:
            year += 1
        try:
            value = date(year, month, day)
        except ValueError:
            continue
        at = clock_at(value, tail[:50])
        found.append((value, at))
        previous, previous_end = value, match.end()
    # A range can abbreviate its end to just the day: 10.1. ~ 13.(화).
    if previous and re.search(r"[~～]", text[previous_end:]):
        tail = text[previous_end:]
        end = re.match(r"\s*\.?\s*(?:\([^)]{1,10}\)\s*)?[~～]\s*(\d{1,2})(?:\s*일|\.|(?=\s|$))", tail)
        if not end:
            return []  # Incomplete periods must not turn a start date into a deadline.
        try:
            end_date = date(previous.year, previous.month, int(end[1]))
        except ValueError:
            return []
        if end_date < previous:
            return []
        at = clock_at(end_date, tail[end.end():])
        found.append((end_date, at))
    return found


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    keys = ("mode", "articleNo") if parts.hostname == "cnuint.cnu.ac.kr" else ("mode", "no", "code", "site_dvs_cd", "menu_dvs_cd")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(
        [(key, query[key][0]) for key in keys if key in query]), ""))


def parse_listing(html: bytes | str, category: str, url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    selector = "a[href*='articleNo=']" if category == "international" else "a[href*='mode=V']"
    links = (soup.select(".bodo_listThum h4 a[href*='mode=V']") if category == "event"
             else [a for a in soup.select(selector) if a.find_parent("tr")])
    if not links and not re.search(r"게시물(?:이|은)?\s*없|등록된\s*게시글이\s*없", soup.get_text()):
        raise ValueError("notice_list_structure_changed")
    rows = {}
    for link in links:
        title = clean(link.get_text(" ", strip=True))
        if not title or RESULT_TITLE.search(title):
            continue
        tr = link.find_parent("tr")
        raw_date = ""
        closed = False
        if category == "event":
            container = link.find_parent(class_="bodo_listThum")
            raw_date = next((li.get_text(" ", strip=True) for li in container.select(".infomation li")
                             if "등록일" in li.get_text()), "")
        elif category == "international":
            node = tr.select_one(".b-date")
            raw_date = node.get_text(" ", strip=True) if node else ""
        else:
            # Recruitment has two .date cells: application period, publication.
            # Only the cell containing a single full date is the publication.
            date_nodes = tr.select("td.date")
            raw_date = next((td.get_text(strip=True) for td in reversed(date_nodes)
                             if re.fullmatch(r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}", td.get_text(strip=True))), "")
            closed = any(td.get_text(strip=True) == "마감" for td in date_nodes)
        if not raw_date and category == "international":
            cells = tr.find_all("td", recursive=False)
            raw_date = cells[-2].get_text(strip=True) if len(cells) >= 5 else ""
        if not raw_date and tr:
            # Pinned rows on some CNU boards use .center rather than .date.
            raw_date = next((td.get_text(strip=True) for td in tr.find_all("td", recursive=False)
                             if re.fullmatch(r"20\d{2}[-./]\d{1,2}[-./]\d{1,2}", td.get_text(strip=True))), "")
        parsed = dates_in(raw_date, datetime.now(KST).date())
        if not parsed:
            raise ValueError("notice_publication_date_missing")
        href = canonical_url(urljoin(url, link["href"]))
        if urlsplit(href).hostname != urlsplit(url).hostname:
            continue
        stable_id = hashlib.sha256(href.encode()).hexdigest()[:16]
        rows[href] = {"id": f"cnu-{stable_id}", "title": title, "url": href, "categories": [category],
                      "source": category, "source_name": SOURCE_NAMES[category], "published_at": parsed[0][0].isoformat()}
        if closed:
            rows[href]["status"] = "closed"
    return list(rows.values())


def body_lines(soup: BeautifulSoup) -> list[str]:
    lines = []
    for node in soup.select(".fr-view, .board_viewDetail"):
        for unwanted in node.select("script, style, iframe"):
            unwanted.decompose()
        blocks = node.select("p, tr, li")
        if not blocks:
            lines.extend(clean(t) for t in node.get_text("\n", strip=True).splitlines() if clean(t))
        else:
            for block in blocks:
                # Keep table cells together: programme, benefits and restrictions
                # belong to the same row, even when the editor wraps them in <p>.
                table_row = block.find_parent("tr")
                in_body_table = table_row is not None and node in table_row.parents
                if block.name == "tr" or (not in_body_table and not block.select("p, tr, li")):
                    if block.name == "tr":
                        # Extract labelled date columns independently from other
                        # columns such as certificate delivery or result dates.
                        table = block.find_parent("table")
                        header = table.find("tr") if table else None
                        cells = block.find_all(["td", "th"], recursive=False)
                        headers = header.find_all(["td", "th"], recursive=False) if header else []
                        if block != header and len(headers) == len(cells):
                            for label, cell in zip(headers, cells):
                                label_text = clean(label.get_text(" ", strip=True))
                                if DEADLINE_LABEL.search(label_text):
                                    lines.append(label_text + ": " + clean(cell.get_text(" ", strip=True)))
                    value = clean(block.get_text(" ", strip=True))
                    if value:
                        lines.append(value)
    return lines


def excerpt(lines: list[str], pattern: str) -> str:
    for i, line in enumerate(lines):
        if re.search(r"지원\s*내용\s*및\s*제출서류", line):
            continue  # A false-document warning does not describe a benefit.
        if re.fullmatch(r"구분\s+내용\s+장학혜택", line):
            continue
        if re.search(pattern, line):
            # A short heading needs context; a complete table row must not borrow
            # the next programme's benefits or restrictions.
            heading = len(line) < 45 and not re.search(r"\d\s*%|전액|만원|만\s*원|학부생|재학생|휴학생|지원\s*없", line)
            selected = [line] + (lines[i + 1:i + 3] if heading else [])
            text = public_excerpt(clean(" ".join(selected)))
            return text[:160].strip()
    return ""


def parse_detail(html: bytes | str, row: dict) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    if not soup.select(".fr-view, .board_viewDetail"):
        raise ValueError("notice_detail_structure_changed")
    lines = body_lines(soup)
    reference = date.fromisoformat(row["published_at"])
    row = dict(row)
    for li in soup.select(".board_viewInfo li:not(.file)"):
        text = clean(li.get_text(" ", strip=True))
        if text.startswith("등록일"):
            published = dates_in(text, reference)
            if published and published[0][1]:
                row["published_time"] = published[0][1]
    candidates = []
    for li in soup.select(".board_viewInfo li:not(.file)"):
        text = clean(li.get_text(" ", strip=True))
        label = DEADLINE_LABEL.search(text)
        if label:
            text = re.split(r"발표|교부|행사\s*일|교육\s*기간|파견\s*기간", text[label.start():])[0]
            parsed = dates_in(text, reference)
            if parsed and len(parsed) <= 2:
                candidates.append((parsed[-1], text))
    if not candidates:
        for i, line in enumerate(lines):
            label = DEADLINE_LABEL.search(line)
            if not label:
                continue
            text = line[label.start():]
            if not dates_in(text, reference) and len(line) < 70:
                text = " ".join(lines[i:i + 3])
                text = text[DEADLINE_LABEL.search(text).start():]
            text = re.split(r"발표|교부|오리엔테이션|행사\s*일|교육\s*기간|파견\s*기간", text)[0]
            parsed = dates_in(text, reference)
            if parsed and len(parsed) <= 2:
                candidates.append((parsed[-1], text))
    if (not candidates and re.search(r"모집|신청|접수", row["title"])
            and re.search(r"[~～]\s*\d{1,4}\s*[.월/\-]|\d\s*(?:일|\.)?\s*까지", row["title"])):
        parsed = dates_in(row["title"], reference)
        if parsed:
            candidates.append((parsed[-1], row["title"]))
    result = {**row, "detail_status": "ok"}
    unique = {value for value, _ in candidates}
    if len(unique) == 1:
        (deadline, at), evidence = candidates[0]
        result.update(deadline=deadline.isoformat(), deadline_evidence=public_excerpt(evidence)[:240])
        if at:
            result["deadline_at"] = at
    elif len(unique) > 1:
        result["deadline_note"] = "모집 회차별 마감일은 원문 확인"
    result["benefit"] = excerpt(lines, r"지원\s*내용|지급\s*금액|장학\s*(?:금액|혜택)|장학금\s*지원|지원금|활동비|(?:교육비|수강료).*?(?:지원|무료|환급|감면)|등록금\s*전액")
    result["eligibility"] = excerpt(lines, r"지원\s*(?:자격|대상)|신청\s*(?:자격|대상)|선발\s*대상|모집\s*대상|참여\s*대상")
    result["summary"] = excerpt(lines, r"모집\s*(?:개요|인원)|프로그램\s*개요|교육\s*내용|행사\s*명|운영\s*내용")
    result["has_attachments"] = bool(soup.select(".board_viewInfo .file a, .b-file-box a"))
    return result


def _fetch(url: str) -> bytes:
    for attempt in range(2):
        try:
            response = requests.get(url, timeout=(5, 20), headers={"User-Agent": "CNUbot public-notice collector"})
            response.raise_for_status()
            return response.content
        except (requests.Timeout, requests.ConnectionError):
            if attempt:
                raise
            time.sleep(1)


def page_url(url: str, category: str, page: int) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    query.update({"article.offset": [str((page - 1) * 10)], "articleLimit": ["10"]}
                 if category == "international" else {"GotoPage": [str(page)]})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ""))


def scrape(output: str | None = None, pages: int = 3, reuse_recent: bool = False) -> int:
    path = Path(output) if output else data_path()
    previous = read_snapshot(path) if output else read_snapshot()
    if not output and path != SEED_PATH:
        # On first deployment a source can fail before the shared file has ever
        # held it. Retain that source's verified packaged snapshot as well.
        seed = read_snapshot(SEED_PATH)
        missing = {category for category in SOURCES
                   if not previous.get("sources", {}).get(category, {}).get("last_success_at")}
        if missing:
            previous = {**previous, "sources": dict(previous.get("sources", {})),
                        "items": [row for row in previous.get("items", []) if row.get("source") not in missing]}
            previous["items"] += [row for row in seed.get("items", []) if row.get("source") in missing]
            for category in missing:
                if category in seed.get("sources", {}):
                    previous["sources"][category] = seed["sources"][category]
    old = {row["url"]: row for row in previous.get("items", [])}
    now = datetime.now(KST)
    rows, sources, success = {}, {}, 0
    for category, url in SOURCES.items():
        status = previous.get("sources", {}).get(category, {})
        try:
            age = now - datetime.fromisoformat(status["last_success_at"])
            recent = timedelta(0) <= age < timedelta(hours=6)
        except (KeyError, TypeError, ValueError):
            recent = False
        if reuse_recent and path.exists() and recent and status.get("status") == "ok" and not status.get("detail_failures"):
            # A failed source must not cause repeated requests to healthy boards.
            sources[category] = dict(status)
            rows.update({key: row for key, row in old.items() if row.get("source") == category})
            success += 1
            continue
        collected = {}
        try:
            for page in range(1, pages + 1):
                address = page_url(url, category, page)
                for row in parse_listing(_fetch(address), category, address):
                    collected[row["url"]] = row
            success += 1
            sources[category] = {"status": "ok", "last_success_at": now.isoformat(), "count": len(collected), "url": url}
        except (requests.RequestException, ValueError):
            collected = {key: value for key, value in old.items() if value.get("source") == category}
            sources[category] = {**previous.get("sources", {}).get(category, {}), "status": "failed", "count": len(collected), "url": url}
        for key, row in collected.items():
            if sources[category]["status"] == "ok":
                row["last_seen_at"] = now.isoformat()
            rows[key] = row
        for key, row in old.items():
            if (row.get("source") == category and not RESULT_TITLE.search(row["title"])
                    and row.get("published_at", "") >= (now.date() - timedelta(days=120)).isoformat()):
                rows.setdefault(key, row)
    if not success:
        raise RuntimeError("all_notice_sources_failed")

    def enrich(row):
        if sources[row["source"]]["status"] != "ok" or row.get("last_seen_at") != now.isoformat():
            return row
        try:
            return parse_detail(_fetch(row["url"]), row)
        except (requests.RequestException, ValueError):
            return {**old.get(row["url"], {}), **row, "detail_status": "failed"}

    with ThreadPoolExecutor(max_workers=3) as executor:
        items = list(executor.map(enrich, rows.values()))
    for category, status in sources.items():
        status["detail_failures"] = sum(row.get("detail_status") == "failed" for row in items if row["source"] == category)
    payload = {"schema_version": 2, "fetched_at": now.isoformat(), "sources": sources,
               "items": sorted(items, key=lambda r: (r.get("published_time") or r["published_at"], r["id"]), reverse=True)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        temp_path = tmp.name
        json.dump(payload, tmp, ensure_ascii=False, indent=2)
        tmp.write("\n")
    try:
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return len(items)


if __name__ == "__main__":
    print(scrape())
