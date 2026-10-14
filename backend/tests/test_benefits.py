import asyncio
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import requests
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.jobs.collect_benefits import due
from app.routers.benefits import router
from app.scrapers import benefits as scraper
from app.services import benefits
from app.utils.benefits_data import KST, read_snapshot

NOW = datetime(2026, 10, 13, 14, 0, tzinfo=KST)


def item(number=0, category="international", **fields):
    return {"id": f"notice-{number}", "title": f"학생 모집 공고 {number}",
            "url": f"https://example.com/notice/{number}", "categories": [category],
            "source": category, "source_name": "공식 모집", "published_at": "2026-10-12", **fields}


def listing(category="scholarship"):
    if category == "international":
        return '''<table><tr><td><a href="?mode=view&amp;articleNo=123&amp;article.offset=10">방문학생 모집 (~10.13. 15:00)</a>
        <span class="b-date">26.10.06</span></td></tr>
        <tr><td><a href="?mode=view&amp;articleNo=124">방문학생 합격자 발표</a><span class="b-date">26.10.07</span></td></tr></table>'''
    return '''<table><tr><td class="title"><a href="?mode=V&amp;no=123&amp;code=sub07_0713&amp;GotoPage=2">장학생 모집</a></td>
    <td class="date">2026-10-12</td></tr></table>'''


class NoticeParsingTest(unittest.TestCase):
    def test_network_timeout_retries_once_and_http_errors_are_not_parsed(self):
        from unittest.mock import Mock
        response = Mock(content=b"public HTML")
        with patch.object(scraper.requests, "get", side_effect=[requests.Timeout(), response]) as get, patch.object(scraper.time, "sleep"):
            self.assertEqual(scraper._fetch("https://example.com"), b"public HTML")
            self.assertEqual(get.call_count, 2)
        response.raise_for_status.side_effect = requests.HTTPError()
        with patch.object(scraper.requests, "get", return_value=response) as get:
            with self.assertRaises(requests.HTTPError):
                scraper._fetch("https://example.com")
            self.assertEqual(get.call_count, 1)

    def test_retry_only_fetches_failed_source_and_keeps_recent_source(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "benefits.json"
            recent = datetime.now(KST).isoformat()
            old = item(category="scholarship")
            payload = {"schema_version": 2, "items": [old], "sources": {
                "scholarship": {"status": "ok", "last_success_at": recent},
                "international": {"status": "failed"}}}
            target.write_text(json.dumps(payload))
            sources = {key: scraper.SOURCES[key] for key in ["scholarship", "international"]}
            def fetch(url):
                self.assertIn("cnuint", url)
                return '<div class="fr-view"></div>' if "mode=view" in url else listing("international")
            with patch.object(scraper, "SOURCES", sources), patch.object(scraper, "_fetch", side_effect=fetch):
                scraper.scrape(str(target), pages=1, reuse_recent=True)
            saved = json.loads(target.read_text())
            self.assertIn(old, saved["items"])
            self.assertEqual(saved["sources"]["scholarship"]["last_success_at"], recent)
            self.assertEqual(saved["sources"]["international"]["status"], "ok")

    def test_official_listing_date_and_canonical_link(self):
        rows = scraper.parse_listing(listing(), "scholarship", scraper.SOURCES["scholarship"])
        self.assertEqual(rows[0]["published_at"], "2026-10-12")
        self.assertNotIn("GotoPage", rows[0]["url"])

    def test_international_listing_excludes_results_and_is_separate_from_academic(self):
        rows = scraper.parse_listing(listing("international"), "international", scraper.SOURCES["international"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["published_at"], "2026-10-06")
        self.assertEqual(rows[0]["url"], "https://cnuint.cnu.ac.kr/cnuint/notice/recruit.do?mode=view&articleNo=123")
        self.assertNotEqual(scraper.SOURCES["international"], scraper.SOURCES["academic"])

    def test_recruitment_uses_publication_cell_not_reception_period(self):
        html = '''<table><tr><td><a href="?mode=V&amp;no=123">직원 모집</a></td>
        <td class="date">2026-10-13~2026-10-23</td><td class="date">2026-10-01</td></tr>
        <tr><td><a href="?mode=V&amp;no=124">연구원 모집</a></td>
        <td class="date">마감</td><td class="date">2026-09-30</td></tr></table>'''
        rows = scraper.parse_listing(html, "recruitment", scraper.SOURCES["recruitment"])
        self.assertEqual(rows[0]["published_at"], "2026-10-01")
        self.assertEqual(rows[1]["status"], "closed")

    def test_event_gallery_does_not_duplicate_description_links_as_titles(self):
        html = '''<div class="bodo_listThum"><a href="?mode=V&amp;no=1"><img></a><div class="view">
        <h4><a href="?mode=V&amp;no=1">교내 워크숍</a></h4>
        <p><a href="?mode=V&amp;no=1">긴 소개 문장</a></p>
        <ul class="infomation"><li>등록일: 2026-10-08</li></ul></div></div>'''
        rows = scraper.parse_listing(html, "event", scraper.SOURCES["event"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "교내 워크숍")
        self.assertEqual(rows[0]["published_at"], "2026-10-08")

    def test_deadline_does_not_use_publication_announcement_or_event_date(self):
        html = '''<ul class="board_viewInfo"><li>등록일 2026-10-12</li></ul>
        <div class="board_viewDetail"><p>행사일: 2026.10.20.</p><p>합격자 발표: 2026.10.22.</p></div>'''
        result = scraper.parse_detail(html, item())
        self.assertNotIn("deadline", result)
        self.assertNotIn("등록일", result["summary"])

    def test_explicit_application_time_and_benefit_table_keep_context(self):
        html = '''<div class="fr-view"><p><span>온라인 지원서 작성 기간:</span><span>2026.10.13.(화) 15:00까지</span></p>
        <p>선발자 발표: 2026.10.16.</p>
        <table><tr><td>구분</td><td>내용</td><td>장학혜택</td></tr>
        <tr><td><p>글로벌인재양성</p></td><td><p>정규학점</p></td><td><p>프로그램 비용 70% 장학금 지원</p></td></tr>
        <tr><td>자비연수</td><td>학점 취득</td><td>지원 없음</td></tr></table>
        <p>지원 자격(글로벌인재양성)</p><p>1학기 이상 수료한 학부생</p></div>'''
        result = scraper.parse_detail(html, item())
        self.assertEqual(result["deadline"], "2026-10-13")
        self.assertEqual(result["deadline_at"], "2026-10-13T15:00:00+09:00")
        self.assertIn("글로벌인재양성", result["benefit"])
        self.assertIn("70%", result["benefit"])
        self.assertNotIn("자비연수", result["benefit"])
        self.assertIn("학부생", result["eligibility"])
        card = benefits.card(result)
        self.assertIn("70%", card["description"])
        self.assertIn("학부생", card["description"])

    def test_metadata_reception_period_works_for_attachment_only_post(self):
        html = '''<ul class="board_viewInfo"><li>등록일 2026-10-12</li>
        <li>접수기간 2026-10-12~2026-10-16</li><li class="file"><a href="file.pdf">접수기간 2026-10-30.pdf</a></li></ul>
        <div class="board_viewDetail"><iframe src="viewer"></iframe></div>'''
        result = scraper.parse_detail(html, item())
        self.assertEqual(result["deadline"], "2026-10-16")
        self.assertFalse(result["eligibility"])
        self.assertTrue(result["has_attachments"])

    def test_normalize_short_dates_day_only_ranges_and_new_year(self):
        for text, expected in [("26.10.06", "2026-10-06"), ("2026-9-2", "2026-09-02"),
                               ("2026.12.24 ~ 1.2.", "2027-01-02"),
                               ("2026.10.1.(목) ~ 13.(화) 15:00", "2026-10-13")]:
            self.assertEqual(scraper.dates_in(text, date(2026, 10, 1))[-1][0].isoformat(), expected)
        self.assertEqual(scraper.dates_in("2026.10.1 ~ 미정", date(2026, 10, 1)), [])

    def test_multiple_rounds_do_not_invent_one_deadline(self):
        result = scraper.parse_detail('<div class="fr-view"><p>1차 신청기간: 2026.10.1 ~ 10.13</p><p>2차 신청기간: 2026.11.1 ~ 11.13</p></div>', item())
        self.assertNotIn("deadline", result)
        self.assertIn("회차", result["deadline_note"])

    def test_fraction_footnote_and_time_range_in_event_title_are_not_deadlines(self):
        for fraction in ["1/3선", "1/3"]:
            result = scraper.parse_detail(f'<div class="board_viewDetail"><p>신청기한: 2026.10.8.(목) 18:00까지 [수업일수 {fraction}]</p></div>', item())
            self.assertEqual(result["deadline"], "2026-10-08")
        result = scraper.parse_detail('<div class="board_viewDetail"></div>', item(title="모집설명회 (9월 18일, 11:00~12:00)"))
        self.assertNotIn("deadline", result)

    def test_reception_table_does_not_confuse_certificate_delivery_date(self):
        html = '''<div class="board_viewDetail"><p>1. 접수기간</p><table>
        <tr><td>구분</td><td>접수기간</td><td>자격증 교부</td></tr>
        <tr><td>제4차</td><td>10.1.(목) ~ 10.13.(화)</td><td>12.4.(금)</td></tr></table></div>'''
        result = scraper.parse_detail(html, item())
        self.assertEqual(result["deadline"], "2026-10-13")

    def test_korean_clock_and_midnight_are_honoured(self):
        for text, expected in [("2026.10.13.(화) 오후 5시까지", "2026-10-13T17:00:00+09:00"),
                               ("2026.10.13.(화) 23시 59분까지", "2026-10-13T23:59:00+09:00"),
                               ("2026.10.13.(화) 오후 23시 59분", "2026-10-13T23:59:00+09:00"),
                               ("2026.10.13.(화) 24:00까지", "2026-10-14T00:00:00+09:00")]:
            result = scraper.parse_detail(f'<div class="board_viewDetail"><p>접수기간: {text}</p></div>', item())
            self.assertEqual(result["deadline_at"], expected)

    def test_false_document_warning_is_not_presented_as_a_benefit(self):
        html = '<div class="fr-view"><p>※ 지원 내용 및 제출서류 등이 사실과 다를 경우, 선발이 취소될 수 있음</p><p>지원 자격: 학부생</p></div>'
        result = scraper.parse_detail(html, item())
        self.assertEqual(result["benefit"], "")

    def test_contacts_are_not_saved_in_public_excerpts_or_deadline_evidence(self):
        html = '<div class="fr-view"><p>신청 마감일: 2026.10.13. 15:00 문의처 담당자 test-contact@example.com 010-1234-5678</p><p>지원내용: 등록금 전액 문의처 test-contact@example.com</p></div>'
        result = scraper.parse_detail(html, item())
        self.assertEqual(result["deadline"], "2026-10-13")
        self.assertNotIn("@", result["deadline_evidence"])
        self.assertNotIn("@", result["benefit"])
        self.assertNotIn("담당자", result["deadline_evidence"])

    def test_structure_or_missing_publication_fail_instead_of_empty_success(self):
        with self.assertRaises(ValueError):
            scraper.parse_listing("<html>maintenance</html>", "scholarship", scraper.SOURCES["scholarship"])
        with self.assertRaises(ValueError):
            scraper.parse_listing('<table><tr><td><a href="?mode=V&no=1">모집</a></td></tr></table>', "scholarship", scraper.SOURCES["scholarship"])

    def test_partial_failure_retains_source_and_all_failure_keeps_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "benefits.json"
            old = item(category="international")
            snapshot = {"schema_version": 2, "items": [old], "sources": {"international": {"last_success_at": NOW.isoformat()}}}
            path.write_text(json.dumps(snapshot))

            def fetch(url):
                if "cnuint" in url:
                    raise requests.ConnectionError()
                if "mode=V" in url:
                    return b'<div class="board_viewDetail"></div>'
                return listing()

            with patch.object(scraper, "_fetch", side_effect=fetch):
                scraper.scrape(str(path), pages=1)
            data = json.loads(path.read_text())
            self.assertIn(old, data["items"])
            self.assertEqual(data["sources"]["international"]["status"], "failed")
            before = path.read_bytes()
            with patch.object(scraper, "_fetch", side_effect=requests.ConnectionError()):
                with self.assertRaises(RuntimeError):
                    scraper.scrape(str(path), pages=1)
            self.assertEqual(before, path.read_bytes())

    def test_legacy_bad_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data.json"
            path.write_text(json.dumps({"items": [item(deadline="2026-9-2")]}))
            self.assertEqual(read_snapshot(path), {})

    def test_first_shared_snapshot_failure_keeps_verified_packaged_source(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "benefits.json"
            previous = {"schema_version": 2, "items": [],
                        "sources": {"international": {"status": "failed"}}}
            old = item(category="international")
            seed = {"schema_version": 2, "items": [old],
                    "sources": {"international": {"status": "ok", "last_success_at": NOW.isoformat()}}}
            def fetch(url):
                if "cnuint" in url:
                    raise requests.ConnectionError()
                return '<div class="board_viewDetail"></div>' if "mode=V" in url else listing()
            sources = {key: scraper.SOURCES[key] for key in ["scholarship", "international"]}
            with patch.object(scraper, "data_path", return_value=target), patch.object(scraper, "SOURCES", sources), \
                 patch.object(scraper, "read_snapshot", side_effect=lambda path=None: seed if path == scraper.SEED_PATH else previous), \
                 patch.object(scraper, "_fetch", side_effect=fetch):
                scraper.scrape(pages=1)
            data = json.loads(target.read_text())
            self.assertIn(old, data["items"])
            self.assertEqual(data["sources"]["international"]["status"], "failed")
            self.assertEqual(data["sources"]["international"]["last_success_at"], NOW.isoformat())


class NoticeExperienceTest(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(benefits, "now_kst", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_latest_sorts_by_publication_and_urgent_excludes_unknown_expired(self):
        snapshot = {"items": [item(0, published_at="2026-10-10"),
                              item(1, published_at="2026-10-12", deadline="2026-10-13", deadline_at="2026-10-13T13:00:00+09:00"),
                              item(2, published_at="2026-10-11", deadline="2026-10-15"),
                              item(3, published_at="2026-01-01")]}
        self.assertEqual([r["id"] for r in benefits._items("학교혜택 최신", snapshot)], ["notice-2", "notice-0"])
        self.assertEqual([r["id"] for r in benefits._items("학교혜택 마감임박", snapshot)], ["notice-2"])

    def test_academic_information_is_not_presented_as_an_unknown_application(self):
        result = benefits.card(item(category="academic", title="학생 출석인정 관련 안내"))
        self.assertIn("정보 안내", result["description"])
        self.assertNotIn("마감 미확인", result["description"])
        self.assertNotIn("모집내용", result["description"])

    def test_paging_preserves_filter_snapshot_moves_to_third_and_back(self):
        snapshot = {"items": [item(n) for n in range(14)] + [item(20, category="academic")]}
        state, _ = benefits.transition(None, "학교혜택 해외교류", snapshot, NOW)
        ids = [r["id"] for r in state["items"]]
        for expected in [1, 2, 2]:
            state, _ = benefits.transition(state, "학교혜택 다음", {"items": [item(99)]}, NOW)
            self.assertEqual(state["page"], expected)
            self.assertEqual(state["selection"], "학교혜택 해외교류")
            self.assertEqual([r["id"] for r in state["items"]], ids)
        state, _ = benefits.transition(state, "학교혜택 이전", {}, NOW)
        self.assertEqual(state["page"], 1)
        state, _ = benefits.transition(state, "학교혜택 학사정보", snapshot, NOW)
        self.assertEqual(state["page"], 0)
        self.assertEqual([r["id"] for r in state["items"]], ["notice-20"])

    def test_expired_or_absent_state_restarts_latest_with_explanation(self):
        state, _ = benefits.transition(None, "학교혜택 교육", {"items": []}, NOW - timedelta(minutes=31))
        for original in [None, state]:
            result, notice = benefits.transition(original, "학교혜택 다음", {"items": [item()]}, NOW)
            self.assertEqual(result["selection"], "학교혜택 최신")
            self.assertEqual(result["page"], 0)
            self.assertIn("만료", notice)

    def test_cross_board_repost_is_shown_once_and_remains_in_both_categories(self):
        original = item(0, title="겨울 단기 파견 방문학생 추가 모집 (~10.13. 15:00)",
                        published_at="2026-10-06", deadline="2026-10-13", deadline_at="2026-10-13T15:00:00+09:00", benefit="프로그램 비용 지원")
        repost = item(1, "academic", title="겨울 단기 파견 방문학생 추가 모집 안내", published_at="2026-10-07", deadline="2026-10-13")
        later_round = item(2, "academic", title="겨울 단기 파견 방문학생 추가 모집 안내", deadline="2026-10-20")
        snapshot = {"items": [original, repost, later_round]}
        urgent = benefits._items("학교혜택 마감임박", snapshot)
        self.assertEqual(len(urgent), 2)
        self.assertEqual(urgent[0]["id"], original["id"])
        self.assertEqual(set(urgent[0]["categories"]), {"international", "academic"})
        self.assertEqual(len(benefits._items("학교혜택 해외교류", snapshot)), 1)
        self.assertEqual(len(benefits._items("학교혜택 학사정보", snapshot)), 2)
        self.assertEqual(original["categories"], ["international"])

    def test_reply_limits_registered_messages_and_direct_original_link(self):
        items = [item(n, benefit="장학금 지원", eligibility="학부생") for n in range(14)]
        allowed = {m for _, m in benefits.CHOICES} | {"학교혜택 다음", "학교혜택 이전", benefits.CATEGORY_MENU_MESSAGE}
        docs = (Path(__file__).resolve().parents[2] / "docs/kakao-message-routing.md").read_text()
        for choice in allowed:
            self.assertIn(choice, docs)
        for selection in [m for _, m in benefits.CHOICES]:
            for page in [0, 1, 2]:
                response = benefits.render(selection, items, page, {"fetched_at": NOW.isoformat()})
                replies = response["template"]["quickReplies"]
                self.assertLessEqual(len(replies), 4)
                self.assertTrue({r["messageText"] for r in replies} <= allowed)
                cards = response["template"]["outputs"][1]["carousel"]["items"]
                self.assertLessEqual(len(cards), 5)
                for card in cards:
                    self.assertLessEqual(len(card["title"]), 50)
                    self.assertLessEqual(len(card["description"]), 128)
                    self.assertEqual(card["buttons"][0]["action"], "webLink")

        home = benefits.render("학교혜택 최신", items, 0, {"fetched_at": NOW.isoformat()}, show_intro=True)
        self.assertEqual([r["label"] for r in home["template"]["quickReplies"]],
                         ["마감임박", "분야 더 보기", "▶️"])
        menu = benefits.category_menu_response()["template"]
        self.assertEqual(len(menu["outputs"]), 1)
        carousel = menu["outputs"][0]["carousel"]
        self.assertEqual(carousel["type"], "textCard")
        self.assertEqual(len(carousel["items"]), 3)
        self.assertEqual(len(menu["quickReplies"]), 2)
        messages = []
        for card in carousel["items"]:
            self.assertLessEqual(len(card["description"]), 128)
            buttons = card["buttons"]
            self.assertLessEqual(len(buttons), 3)
            self.assertTrue(all(b["action"] == "message" for b in buttons))
            messages += [b["messageText"] for b in buttons]
        self.assertEqual(set(messages), {f"학교혜택 {name}" for name in benefits.CATEGORIES})
        self.assertTrue(set(messages) <= allowed)

    def test_stale_and_partial_source_dates_are_not_presented_as_fresh(self):
        snapshot = {"fetched_at": NOW.isoformat(), "sources": {
            "international": {"status": "failed", "last_success_at": (NOW - timedelta(days=2)).isoformat()},
            "education": {"status": "ok", "last_success_at": NOW.isoformat()}}}
        response = benefits.render("학교혜택 해외교류", [item()], 0, snapshot)
        text = response["template"]["outputs"][0]["simpleText"]["text"]
        self.assertIn("10.11", text)
        self.assertIn("갱신 지연", text)

    def test_collector_refreshes_old_or_failed_sources_and_skips_recent(self):
        sources = {c: {"status": "ok", "last_success_at": NOW.isoformat()} for c in scraper.SOURCES}
        self.assertFalse(due(NOW, {"sources": sources}))
        self.assertTrue(due(NOW + timedelta(hours=6), {"sources": sources}))
        sources["international"]["status"] = "failed"
        self.assertTrue(due(NOW, {"sources": sources}))


class FakeConnection:
    def __init__(self):
        self.states = {}
        self.keys = []
        self.lock = asyncio.Lock()

    def transaction(self):
        return self.lock

    async def execute(self, query, *args):
        if query.lstrip().startswith("INSERT"):
            self.keys.append(args[0])
            self.states[args[0]] = json.loads(args[1])

    async def fetchrow(self, query, key):
        return {"state": json.dumps(self.states[key])} if key in self.states else None


class Acquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *args):
        pass


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        return Acquire(self.conn)


class NoticeDatabaseTest(unittest.IsolatedAsyncioTestCase):
    async def test_category_menu_preserves_browsing_without_accessing_database(self):
        from app import database
        with patch.object(database, "get_pool", side_effect=AssertionError("Menu must not touch browsing state")) as pool:
            response = await benefits.browse_response(benefits.CATEGORY_MENU_MESSAGE, "test-user")
        pool.assert_not_called()
        self.assertEqual(len(response["template"]["outputs"]), 1)
        self.assertEqual(len(response["template"]["outputs"][0]["carousel"]["items"]), 3)

    async def test_state_survives_requests_isolated_per_user_and_no_raw_user_id(self):
        from app import database
        conn = FakeConnection()
        snapshot = {"schema_version": 2, "fetched_at": NOW.isoformat(), "items": [item(n) for n in range(14)]}
        with patch.object(database, "get_pool", return_value=FakePool(conn)), patch.object(benefits, "read_snapshot", return_value=snapshot), patch.object(benefits, "now_kst", return_value=NOW):
            await benefits.browse_response("학교혜택 해외교류", "test-user-a")
            await benefits.browse_response("학교혜택 최신", "test-user-b")
            await asyncio.gather(benefits.browse_response("학교혜택 다음", "test-user-a"), benefits.browse_response("학교혜택 다음", "test-user-a"))
            pages = {s["selection"]: s["page"] for s in conn.states.values()}
            self.assertEqual(pages, {"학교혜택 해외교류": 2, "학교혜택 최신": 0})
        self.assertEqual(len(conn.states), 2)
        self.assertTrue(all(len(k) == 64 and "test-user" not in k for k in conn.keys))

    async def test_unavailable_database_or_user_id_has_no_misleading_page_button(self):
        from app import database
        snapshot = {"schema_version": 2, "items": [item(n) for n in range(14)]}
        with patch.object(database, "get_pool", side_effect=RuntimeError()), patch.object(benefits, "read_snapshot", return_value=snapshot), patch.object(benefits, "now_kst", return_value=NOW):
            for user in [None, "test-user"]:
                response = await benefits.browse_response("학교혜택 다음", user)
                messages = [r["messageText"] for r in response["template"]["quickReplies"]]
                self.assertNotIn("학교혜택 다음", messages)
                self.assertNotIn("학교혜택 이전", messages)


class NoticeRouteTest(unittest.IsolatedAsyncioTestCase):
    async def test_post_home_list_page_use_kakao_utterance_and_user_identity(self):
        app = FastAPI()
        app.include_router(router, prefix="/benefits")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="https://example.com") as client:
            with patch.object(benefits, "browse_response", return_value={"version": "2.0", "template": {}}) as browse:
                for route, text in [("home", "학교혜택"), ("list", "학교혜택 해외교류"), ("page", "학교혜택 이전")]:
                    response = await client.post(f"/benefits/{route}", json={"userRequest": {"utterance": text, "user": {"id": "test-user"}}})
                    self.assertEqual(response.status_code, 200)
                    if route == "home":
                        browse.assert_awaited_with("학교혜택 최신", "test-user", show_intro=True)
                    else:
                        browse.assert_awaited_with(text, "test-user")


if __name__ == "__main__":
    unittest.main()
