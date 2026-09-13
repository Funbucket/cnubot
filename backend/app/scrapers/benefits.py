"""충남대 백마광장 혜택 게시판 수집기."""
import json
import re
import hashlib
from urllib.parse import urljoin
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SOURCES = {
    "scholarship": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0713&menu_dvs_cd=0713&site_dvs_cd=kr",
    "education": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0704&menu_dvs_cd=0704&site_dvs_cd=kr",
    "internship": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0709&menu_dvs_cd=0709&site_dvs_cd=kr",
    "recruitment": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0705&menu_dvs_cd=0705&site_dvs_cd=kr",
    "international": "https://plus.cnu.ac.kr/_prog/_board/?code=sub07_0702&menu_dvs_cd=0702&site_dvs_cd=kr",
    "event": "https://plus.cnu.ac.kr/_prog/_board/?code=sub010714&menu_dvs_cd=0712&site_dvs_cd=kr",
}


def scrape(output: str = "app/static/data/benefits.json") -> int:
    rows = {}
    for category, url in SOURCES.items():
        soup = BeautifulSoup(requests.get(url, timeout=20).content, "html.parser")
        for link in soup.select("a[href*='mode=V']"):
            title = link.get_text(" ", strip=True)
            href = link.get("href", "")
            if not title or not href or "합격" in title or "결과" in title or "취소" in title:
                continue
            href = urljoin(url, href)
            key = href
            stable_id = hashlib.sha256(key.encode()).hexdigest()[:16]
            row = rows.setdefault(key, {"id": f"cnu-{stable_id}", "title": title, "url": href, "categories": [], "published_at": ""})
            if category not in row["categories"]:
                row["categories"].append(category)
    # 상세 페이지에서 첫 본문과 날짜를 보강한다. 실패해도 목록 공고는 보존한다.
    for row in rows.values():
        try:
            detail = BeautifulSoup(requests.get(row["url"], timeout=15).content, "html.parser")
            text = detail.select_one("#contents") or detail.select_one(".view_cont") or detail.body
            content = text.get_text(" ", strip=True) if text else ""
            content = re.sub(r"\s+", " ", content)
            dates = re.findall(r"20\d{2}[.\-/]\s*\d{1,2}[.\-/]\s*\d{1,2}", content)
            if dates:
                normalized = [re.sub(r"[./]", "-", d).replace(" ", "") for d in dates]
                row["deadline"] = normalized[-1]
            row["summary"] = content[:180]
            for label in ("장학금", "지원금", "교육비", "활동비", "숙박", "항공"):
                pos = content.find(label)
                if pos >= 0:
                    row["benefit"] = content[max(0, pos - 20):pos + 100]
                    break
            row["eligibility"] = "공고 본문·첨부의 지원 대상 확인"
        except requests.RequestException:
            continue
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": datetime.now().isoformat(), "items": list(rows.values())}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(rows)


if __name__ == "__main__":
    print(scrape())
