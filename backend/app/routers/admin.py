import html
import asyncio
import os
import secrets
from typing import Any

from app.services import experiments
from app.services import llm
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field

router = APIRouter()
security = HTTPBasic()


class VariantInput(BaseModel):
    variant_key: str
    label: str
    config: dict[str, Any] = Field(default_factory=dict)
    weight: int = Field(default=50, ge=0)


class ExperimentInput(BaseModel):
    experiment_key: str | None = None
    name: str
    hypothesis: str
    primary_metric: str
    guardrail_metric: str | None = None
    unit: str = "user"
    alpha: float = Field(default=0.05, gt=0, lt=1)
    power: float = Field(default=0.8, gt=0, lt=1)
    baseline_rate: float | None = Field(default=None, gt=0, lt=1)
    mde: float | None = Field(default=0.03, gt=0, lt=1)
    variants: list[VariantInput] = Field(min_length=2)


class SuggestInput(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    expected_username = os.getenv("ADMIN_USERNAME")
    expected_password = os.getenv("ADMIN_PASSWORD")
    valid = bool(expected_username and expected_password) and secrets.compare_digest(
        credentials.username, expected_username
    ) and secrets.compare_digest(credentials.password, expected_password)
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="관리자 인증이 필요합니다.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("", response_class=HTMLResponse)
async def admin_home(_: str = Depends(require_admin)):
    return RedirectResponse("/admin/experiments", status_code=303)


@router.get("/insights", response_class=HTMLResponse)
async def insights(_: str = Depends(require_admin)):
    data = await experiments.get_promotion_insights()
    return HTMLResponse(_insights_page(data))


@router.get("/experiments", response_class=HTMLResponse)
async def experiments_home(_: str = Depends(require_admin)):
    rows = await experiments.list_experiments()
    analyses = await asyncio.gather(
        *(experiments.get_analysis(row["id"]) for row in rows),
        return_exceptions=True,
    )
    for row, analysis in zip(rows, analyses):
        if not isinstance(analysis, Exception):
            row["live_analysis"] = analysis
    cards = "".join(_experiment_card(row) for row in rows)
    return HTMLResponse(_page(cards, len(rows), show_form=False, show_list=True))


@router.get("/experiments/new", response_class=HTMLResponse)
async def new_experiment(_: str = Depends(require_admin)):
    return HTMLResponse(_page("", 0, show_form=True, show_list=False))


@router.post("/experiments")
async def create_experiment(
    payload: ExperimentInput, admin: str = Depends(require_admin)
):
    try:
        experiment_id = await experiments.create_experiment(
            payload.model_dump(), admin
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": experiment_id}


@router.post("/suggest")
async def suggest(payload: SuggestInput, _: str = Depends(require_admin)):
    try:
        return await llm.suggest_experiment(payload.prompt)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/experiments/{experiment_id}/{status}")
async def change_status(experiment_id: int, status: str, _: str = Depends(require_admin)):
    if status not in {"running", "paused", "completed"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 상태입니다.")
    try:
        await experiments.set_experiment_status(experiment_id, status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/experiments/{experiment_id}/results")
async def results(experiment_id: int, _: str = Depends(require_admin)):
    return await experiments.get_analysis(experiment_id)


def _experiment_card(row: dict[str, Any]) -> str:
    variants = "".join(
        f"<li><code>{html.escape(v['variant_key'])}</code>: "
        f"{html.escape(v['label'])} ({v['weight']}%)</li>"
        for v in row["variants"]
    )
    experiment_id = row["id"]
    actions = ""
    if row["status"] == "draft":
        actions = f'<button onclick="statusChange({experiment_id}, \'running\')">시작</button>'
    elif row["status"] == "running":
        actions = f'<button onclick="statusChange({experiment_id}, \'paused\')">일시중지</button>'
    elif row["status"] == "paused":
        actions = f'<button onclick="statusChange({experiment_id}, \'running\')">재개</button>'
    status_label = {"draft": "초안", "running": "실행 중", "paused": "일시중지", "completed": "완료"}.get(row["status"], row["status"])
    sample = row.get("min_sample_size") or "미설정"
    analysis = row.get("live_analysis", {})
    analysis_variants = analysis.get("variants", [])
    exposed = sum(v.get("exposed_users", 0) for v in analysis_variants)
    clicked = sum(v.get("clicked_users", 0) for v in analysis_variants)
    ctr = clicked / exposed * 100 if exposed else 0
    progress = min(
        [v.get("exposed_users", 0) / row["min_sample_size"] * 100 for v in analysis_variants]
        or [0]
    ) if row.get("min_sample_size") else 0
    live_text = f"{exposed:,}명 노출 · {clicked:,}명 클릭 · CTR {ctr:.2f}% · 목표 {min(progress, 100):.0f}%"
    return f"""
    <article class="experiment-card" data-id="{experiment_id}" data-name="{html.escape(row['name'].lower())}" data-status="{row['status']}">
      <div class="card-top"><div><span class="eyebrow">{html.escape(row['experiment_key'])}</span><h3>{html.escape(row['name'])}</h3></div><span class="status status-{row['status']}">{status_label}</span></div>
      <p class="hypothesis">{html.escape(row['hypothesis'])}</p>
      <div class="meta-grid"><div><span>핵심 지표</span><b>{html.escape(row['primary_metric'])}</b></div><div><span>가드레일</span><b>{html.escape(row['guardrail_metric'] or '-')}</b></div><div><span>최소 샘플 / 변형</span><b>{sample}명</b></div><div><span>유의수준 · 검정력</span><b>{row.get('alpha', 0.05):.2f} · {row.get('power', 0.8):.0%}</b></div></div>
      <div class="live-summary" id="live-{experiment_id}"><span class="live-label">실시간 현황</span><b>{live_text}</b><span>SRM {html.escape(analysis.get('srm', {}).get('status', '-'))}</span></div>
      <div class="variants"><h4>변형</h4><ul>{variants}</ul></div>
      <div class="actions">{actions}<button class="secondary" onclick="results({experiment_id})">결과 보기</button></div>
      <div id="result-{experiment_id}" class="result-panel hidden"></div>
    </article>
    """


def _insights_page(data: dict[str, Any]) -> str:
    totals = data["totals"]
    exposed = totals.get("exposed_users") or 0
    clicked = totals.get("clicked_users") or 0
    ctr = clicked / exposed * 100 if exposed else 0
    product_rows = "".join(
        f"<tr><td><b>{html.escape(_insight_label(row['product_key']))}</b><small><code>{html.escape(row['product_key'])}</code></small></td>"
        f"<td data-label=\"노출\">{row['exposed_users']:,}</td><td data-label=\"클릭\">{row['clicked_users']:,}</td>"
        f"<td data-label=\"CTR\"><b>{(row['clicked_users'] / row['exposed_users'] * 100 if row['exposed_users'] else 0):.2f}%</b></td>"
        f"<td data-label=\"클릭 이벤트\">{row['click_events']:,}건</td></tr>"
        for row in data["products"]
    ) or '<tr><td colspan="5" class="sub">아직 수집된 프로모션 데이터가 없습니다.</td></tr>'
    surface_labels = {
        "menu_button": "학식 메뉴 버튼",
        "quick_reply": "스케줄 퀵리플라이",
        "commerce_card": "commerceCard",
        "promotion_block": "기타 프로모션 영역",
    }
    surface_rows = "".join(
        f"<tr><td data-label=\"위치\">{html.escape(surface_labels.get(row['surface'], row['surface']))}</td>"
        f"<td data-label=\"사용자\">{row['users']:,}명</td><td data-label=\"이벤트\">{row['events']:,}건</td></tr>"
        for row in data["surfaces"]
    ) or '<tr><td colspan="3" class="sub">아직 클릭 데이터가 없습니다.</td></tr>'
    daily_rows = "".join(
        f"<tr><td data-label=\"날짜\">{html.escape(str(row['day']))}</td><td data-label=\"노출\">{row['exposed_users']:,}명</td>"
        f"<td data-label=\"클릭 사용자\">{row['clicked_users']:,}명</td><td data-label=\"클릭 이벤트\">{row['click_events']:,}건</td></tr>"
        for row in data["daily"]
    ) or '<tr><td colspan="4" class="sub">아직 일별 데이터가 없습니다.</td></tr>'
    product_sql = """WITH normalized AS (
  SELECT COALESCE(e.properties->>'product_key', v.config->>'product_key', 'unknown') AS product_key,
         e.user_id, e.event_name
  FROM experiment_events e
  LEFT JOIN experiment_variants v ON v.experiment_id = e.experiment_id
    AND v.variant_key = e.variant_key
)
SELECT product_key,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure') AS exposed_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name IN ('promotion_click', 'promotion_button_click', 'promotion_quick_reply_click', 'promotion_block_click', 'commerce_card_click')) AS clicked_users
FROM normalized GROUP BY product_key;"""
    surface_sql = """SELECT CASE
  WHEN event_name = 'promotion_quick_reply_click' THEN 'quick_reply'
  WHEN event_name = 'commerce_card_click' THEN 'commerce_card'
  WHEN event_name = 'promotion_button_click' THEN 'menu_button'
  ELSE 'promotion_block' END AS surface,
  COUNT(DISTINCT user_id) AS users, COUNT(*) AS events
FROM experiment_events
WHERE event_name IN ('promotion_click', 'promotion_button_click', 'promotion_quick_reply_click', 'promotion_block_click', 'commerce_card_click')
GROUP BY 1;"""
    daily_sql = """SELECT (created_at AT TIME ZONE 'Asia/Seoul')::date AS day,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure') AS exposed_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name IN ('promotion_click', 'promotion_button_click', 'promotion_quick_reply_click', 'promotion_block_click', 'commerce_card_click')) AS clicked_users
FROM experiment_events
GROUP BY day ORDER BY day DESC LIMIT 30;"""
    details = lambda query: f'<details><summary>집계 기준 · SQL 보기</summary><pre>{html.escape(query)}</pre></details>'
    page = f"""<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CNU 인사이트</title>
<style>
*{{box-sizing:border-box}}body{{font-family:Inter,system-ui,sans-serif;margin:0;background:#f5f7fb;color:#172033}}.shell{{max-width:1120px;margin:auto;padding:28px 20px 64px}}header{{display:flex;justify-content:space-between;align-items:end;margin-bottom:24px}}h1{{font-size:30px;margin:4px 0 8px;letter-spacing:-.04em}}h2{{font-size:18px;margin:28px 0 10px}}p{{line-height:1.5}}.sub{{color:#71809b}}.eyebrow{{font-size:11px;color:#71809b;font-family:ui-monospace,monospace}}nav{{display:flex;gap:8px}}nav a{{color:#3767e8;text-decoration:none;font-size:13px;font-weight:700;padding:8px 10px;border-radius:8px}}nav a.active{{background:#3767e8;color:#fff}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.metric,.panel{{background:#fff;border:1px solid #e3e8f0;border-radius:14px;box-shadow:0 8px 24px #1720330a}}.metric{{padding:17px}}.metric span{{display:block;color:#71809b;font-size:12px}}.metric b{{display:block;font-size:25px;margin-top:7px;letter-spacing:-.04em}}.metric small{{color:#71809b}}.panel{{padding:18px;overflow:hidden}}.panel-head{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}}.panel-head h2{{margin:0}}.hint{{font-size:12px;color:#71809b}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:12px 8px;text-align:left;border-bottom:1px solid #edf0f5;white-space:nowrap}}th{{font-size:11px;color:#71809b;font-weight:650}}td small{{display:block;color:#8a94a6;margin-top:3px}}code{{font-size:11px;color:#71809b}}details{{margin-top:14px;border-top:1px solid #edf0f5;padding-top:10px}}summary{{cursor:pointer;color:#3767e8;font-size:12px;font-weight:700}}pre{{white-space:pre-wrap;word-break:break-word;background:#f7f9fc;color:#536078;border-radius:9px;padding:12px;font:11px/1.55 ui-monospace,monospace;margin:10px 0 0}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}@media(max-width:720px){{.shell{{padding:20px 14px 40px}}header{{display:block}}nav{{margin-top:16px;flex-wrap:wrap}}nav a{{padding:8px 9px}}h1{{font-size:26px}}.grid,.two{{grid-template-columns:1fr}}.panel{{padding:12px;overflow:visible}}table,thead,tbody,tr,td{{display:block}}thead{{display:none}}tr{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0 12px;padding:10px 2px;border-bottom:1px solid #edf0f5}}tr:last-child{{border-bottom:0}}td{{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding:7px 2px;border:0;white-space:normal;text-align:right}}td::before{{content:attr(data-label);color:#71809b;font-size:11px;text-align:left}}td:first-child{{grid-column:1/-1;display:block;text-align:left;font-size:14px;padding-top:3px}}td:first-child::before{{display:none}}.metric b{{font-size:23px}}}}
</style><body><main class="shell"><header><div><span class="eyebrow">CNU PROMOTION INSIGHTS</span><h1>인사이트 대시보드</h1><p class="sub">수집된 추천 상품 반응을 상품·노출 위치·날짜별로 확인합니다.</p></div><nav><a class="active" href="/admin/insights">인사이트</a><a href="/admin/experiments">실험 목록</a><a href="/admin/experiments/new">＋ 새 실험</a></nav></header>
<section class="grid"><div class="metric"><span>고유 노출 사용자</span><b>{exposed:,}명</b><small>상품 기준 중복 제거</small></div><div class="metric"><span>고유 클릭 사용자</span><b>{clicked:,}명</b><small>버튼·퀵리플라이·commerceCard</small></div><div class="metric"><span>전체 CTR</span><b>{ctr:.2f}%</b><small>{totals.get('events') or 0:,}건의 이벤트 기록</small></div></section>
<h2>상품별 반응</h2><section class="panel"><div class="panel-head"><h2>어떤 상품이 반응이 좋은가</h2><span class="hint">고유 사용자 기준</span></div><table><thead><tr><th>상품</th><th>노출</th><th>클릭</th><th>CTR</th><th>클릭 이벤트</th></tr></thead><tbody>{product_rows}</tbody></table>{details(product_sql)}</section>
<section class="two"><div><h2>노출 위치별 클릭</h2><section class="panel"><table><thead><tr><th>위치</th><th>사용자</th><th>이벤트</th></tr></thead><tbody>{surface_rows}</tbody></table>{details(surface_sql)}</section></div><div><h2>최근 일별 추이</h2><section class="panel"><table><thead><tr><th>날짜</th><th>노출</th><th>클릭 사용자</th><th>클릭 이벤트</th></tr></thead><tbody>{daily_rows}</tbody></table>{details(daily_sql)}</section></div></section>
</main></body></html>"""
    return page


def _insight_label(product_key: str) -> str:
    return {
        "yellow_cheese_buttering": "황치즈 버터링",
        "lactofit_gold": "락토핏 골드",
        "lavender_wipes": "리벤스 라벤더 물티슈",
        "cento_toothbrush": "센토 프라임 칫솔",
        "unknown": "상품 미상",
    }.get(product_key, product_key)


def _page(cards: str, experiment_count: int, show_form: bool = True, show_list: bool = True) -> str:
    card_markup = cards or '<div class="card"><p class="sub">아직 만든 실험이 없습니다. 위에서 첫 가설을 등록해보세요.</p></div>'
    page_mode = "new-page" if show_form and not show_list else "list-page"
    page = """<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CNU 실험실</title>
<style>
*{{box-sizing:border-box}}body{{font-family:Inter,system-ui,sans-serif;margin:0;background:#f5f7fb;color:#172033}}.shell{{max-width:1120px;margin:auto;padding:32px 20px 64px}}header{{display:flex;justify-content:space-between;align-items:end;margin-bottom:28px}}h1{{font-size:30px;margin:4px 0 8px;letter-spacing:-.04em}}h2{{font-size:19px;margin:30px 0 12px}}h3{{font-size:18px;margin:5px 0;letter-spacing:-.02em}}h4{{font-size:13px;margin:18px 0 8px;color:#68738a}}p{{line-height:1.55}}.sub{{color:#68738a;margin:0}}.card,form,.experiment-card{{background:#fff;border:1px solid #e3e8f0;border-radius:16px;padding:22px;margin:14px 0;box-shadow:0 8px 24px #1720330a}}form{{border-top:4px solid #3767e8}}.section-title{{display:flex;justify-content:space-between;align-items:center}}.eyebrow{{font-size:11px;color:#71809b;font-family:ui-monospace,monospace}}label{{display:block;font-size:13px;font-weight:650;color:#3d4960;margin-top:12px}}input,textarea{{width:100%;font:inherit;box-sizing:border-box;margin-top:6px;padding:11px 12px;border:1px solid #d4dbe7;border-radius:9px;background:#fbfcfe}}input:focus,textarea:focus{{outline:3px solid #3767e822;border-color:#3767e8}}textarea{{min-height:76px;resize:vertical}}button{{border:0;border-radius:9px;padding:10px 14px;background:#3767e8;color:#fff;font-weight:700;cursor:pointer;margin:4px 4px 0 0}}button:hover{{filter:brightness(.95)}}button.secondary{{background:#eef2f8;color:#344159}}button:disabled{{opacity:.55;cursor:wait}}.card-top,.row{{display:flex;justify-content:space-between;gap:16px;align-items:center}}.status{{padding:5px 10px;border-radius:99px;font-size:12px;font-weight:700;white-space:nowrap}}.status-draft{{background:#fff4d6;color:#8a6200}}.status-running{{background:#dcf8e8;color:#147342}}.status-paused{{background:#e9edf5;color:#68738a}}.status-completed{{background:#e6edff;color:#3158af}}.hypothesis{{color:#4d5a70;margin:16px 0}}.meta-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.meta-grid div{{padding:12px;background:#f7f9fc;border-radius:10px;min-width:0}}.meta-grid span{{display:block;color:#7b879b;font-size:11px;margin-bottom:5px}}.meta-grid b{{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px}}.variants ul{{list-style:none;padding:0;margin:0;display:flex;gap:8px;flex-wrap:wrap}}.variants li{{background:#f1f4fa;border-radius:8px;padding:8px 10px;font-size:13px}}.actions{{margin-top:18px}.result-panel{{margin-top:14px;border-top:1px solid #e6eaf1;padding-top:14px}}.hidden{{display:none}}.result-summary{{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}}.metric{{background:#f6f8fc;padding:10px 12px;border-radius:9px}}.metric span{{display:block;color:#71809b;font-size:11px}}.metric b{{display:block;margin-top:3px}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:9px;text-align:left;border-bottom:1px solid #edf0f5}}th{{color:#71809b;font-weight:600}}.notice{{padding:12px 14px;background:#fff8e7;border:1px solid #f3dfaa;border-radius:10px;color:#785b12;font-size:13px}}.form-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0 18px}}.wide{{grid-column:1/-1}}.field-help{{display:block;color:#7b879b;font-size:11px;font-weight:400;margin-top:4px}}.form-footer{{display:flex;justify-content:space-between;align-items:center;margin-top:18px;padding-top:16px;border-top:1px solid #edf0f5}}.toolbar{{display:flex;gap:8px;align-items:center;margin:12px 0}}.toolbar input{{margin:0;max-width:280px}}.count{{color:#71809b;font-size:12px}}@media(max-width:720px){{.meta-grid{{grid-template-columns:repeat(2,1fr)}}.form-grid{{display:block}}header{{display:block}}.notice{{margin-top:18px}}.toolbar{{align-items:stretch;flex-direction:column}.toolbar input{{max-width:none}}}}
/* Mobile-first refinements */
@media(max-width:720px){{
  body{{font-size:14px}}.shell{{padding:20px 14px 40px}}
  .card,form,.experiment-card{{padding:16px;border-radius:14px;margin:10px 0}}
  header{{display:block;margin-bottom:18px}}h1{{font-size:26px}}h2{{font-size:17px;margin:22px 0 10px}}
  .notice{{margin-top:16px;font-size:12px}}.form-grid{{display:block}}
  input,textarea,select{{font-size:16px;padding:12px}}textarea{{min-height:88px}}
  form>button{{width:100%;margin:10px 0 4px}}.form-footer{{display:block}}
  .form-footer button{{width:100%;margin-top:12px;padding:13px}}
  .meta-grid{{grid-template-columns:repeat(2,1fr);gap:7px}}.meta-grid div{{padding:10px}}
  .meta-grid b{{font-size:12px}}.card-top{{align-items:flex-start;gap:8px}}
  .card-top h3{{max-width:215px}}.actions{{display:grid;grid-template-columns:1fr 1fr;gap:8px}}
  .actions button{{width:100%;margin:0;padding:11px 8px}}.variants li{{flex:1 1 100%;font-size:12px}}
  .toolbar{{align-items:stretch;flex-direction:column}}.toolbar input{{max-width:none}}
  .toolbar select{{margin-top:0}}.result-panel{{margin-left:-4px;margin-right:-4px;padding-left:4px;padding-right:4px}}
}}
 .new-page .page-list{{display:none}}.list-page #new-experiment{{display:none}}nav{{display:flex;gap:8px;margin-bottom:12px}}nav a{{color:#3767e8;text-decoration:none;font-size:13px;font-weight:700;padding:8px 10px;border-radius:8px}}nav a.nav-primary{{background:#3767e8;color:#fff}}.event-metric{{min-width:150px}}.event-metric small{{display:block;color:#8a94a6;margin-top:3px}}
 .live-summary{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:16px 0 4px;padding:12px;background:#f7f9fc;border-radius:10px;color:#536078;font-size:12px}}.live-label{{color:#3767e8;font-weight:800}}.live-loading{{color:#8a94a6}}.progress{{flex:1;min-width:80px;height:6px;background:#e2e7f0;border-radius:99px;overflow:hidden}}.progress i{{display:block;height:100%;background:#3767e8;border-radius:inherit}}.srm{{font-weight:700}}
</style>
<body class="__PAGE_MODE__"><main class="shell"><header><div><span class="eyebrow">CNU EXPERIMENT LAB</span><h1>실험실</h1><p class="sub">가설을 검증하고, 학습을 기록하세요.</p></div><div><nav><a href="/admin/insights">인사이트</a><a href="/admin/experiments">실험 목록</a><a class="nav-primary" href="/admin/experiments/new">＋ 새 실험</a></nav><div class="notice">결정 전 샘플 수와 SRM을 확인하세요.</div></div></header>
<form id="new-experiment">
<div class="section-title"><h2>새 실험 설계</h2><span class="eyebrow">STEP 1 · PLAN</span></div>
<label class="wide">AI에게 설계 요청<textarea id="ai-prompt" placeholder="예: 황치즈 버터링 특가 버튼 문구의 클릭률을 높일 수 있는 A/B 실험을 설계해줘"></textarea><span class="field-help">가설·지표·변형 문구 초안을 자동으로 채워줍니다.</span></label>
<button type="button" onclick="aiSuggest()">✨ AI 실험 초안 만들기</button>
<div class="form-grid">
<label>실험 키<input name="experiment_key" placeholder="비워두면 자동 생성"></label>
<label>실험 이름<input name="name" placeholder="간식 특가 버튼 문구 테스트" required></label>
<label>가설<textarea name="hypothesis" required>상품 중심 문구가 일반 문구보다 클릭률을 높인다.</textarea></label>
<label>핵심 지표<input name="primary_metric" value="promotion_click_rate" required></label>
<label>가드레일 지표<input name="guardrail_metric" value="menu_response_error_rate"></label>
<label>기준 전환율<input name="baseline_rate" type="number" step="0.001" min="0.001" max="0.999" placeholder="예: 0.05"></label>
<label>최소 검출 효과(MDE)<input name="mde" type="number" step="0.001" min="0.001" max="0.999" value="0.03"><span class="field-help">기본 3%p · 작은 실험에서도 확인 가능한 현실적인 차이</span></label>
<label>유의수준 α<input name="alpha" type="number" step="0.01" value="0.05"></label>
<label>검정력 power<input name="power" type="number" step="0.05" value="0.8"></label>
<label>A 변형 키<input name="a_key" value="control"></label><label>A 버튼 문구<input name="a_label" value="간식 특가"></label>
<label>B 변형 키<input name="b_key" value="treatment"></label><label>B 버튼 문구<input name="b_label" value="황치즈 버터링 특가"></label>
</div><div class="form-footer"><span class="field-help">실험 키를 비우면 이름을 기반으로 자동 생성됩니다.</span><button>실험 초안 저장 →</button></div>
</form>
<section class="page-list"><div class="section-title"><h2>실험 목록</h2><span class="eyebrow">__EXPERIMENT_COUNT__ EXPERIMENTS</span></div><div class="toolbar"><input id="search" placeholder="실험 이름 검색"><select id="status-filter"><option value="">모든 상태</option><option value="draft">초안</option><option value="running">실행 중</option><option value="paused">일시중지</option><option value="completed">완료</option></select><span class="count" id="visible-count"></span></div><section id="experiment-list">__CARDS__</section></section></main>
<script>
const form=document.querySelector('#new-experiment');
async function aiSuggest(){{const prompt=document.querySelector('#ai-prompt').value;if(!prompt)return alert('AI에게 요청할 내용을 입력하세요.');const r=await fetch('/admin/suggest',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{prompt}})}});if(!r.ok)return alert(await r.text());const d=await r.json();form.name.value=d.name||'';form.hypothesis.value=d.hypothesis||'';form.primary_metric.value=d.primary_metric||'';form.guardrail_metric.value=d.guardrail_metric||'';if(d.variants?.length>=2){{form.a_key.value=d.variants[0].variant_key;form.a_label.value=d.variants[0].label;form.b_key.value=d.variants[1].variant_key;form.b_label.value=d.variants[1].label;}}}}
form?.addEventListener('submit',async(e)=>{{e.preventDefault();const f=new FormData(form);const num=(name)=>f.get(name)?Number(f.get(name)):null;const body={{experiment_key:f.get('experiment_key')||null,name:f.get('name'),hypothesis:f.get('hypothesis'),primary_metric:f.get('primary_metric'),guardrail_metric:f.get('guardrail_metric'),alpha:num('alpha'),power:num('power'),baseline_rate:num('baseline_rate'),mde:num('mde'),variants:[{{variant_key:f.get('a_key'),label:f.get('a_label'),weight:50,config:{{button_label:f.get('a_label')}}}},{{variant_key:f.get('b_key'),label:f.get('b_label'),weight:50,config:{{button_label:f.get('b_label')}}}}]}};const r=await fetch('/admin/experiments',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});if(r.ok)location.reload();else alert(await r.text())}});
async function statusChange(id,status){{await fetch(`/admin/experiments/${{id}}/${{status}}`,{{method:'POST'}});location.reload()}}
function filterExperiments(){{const query=document.querySelector('#search').value.toLowerCase();const status=document.querySelector('#status-filter').value;const cards=document.querySelectorAll('.experiment-card');let visible=0;cards.forEach(card=>{{const show=(!query||card.dataset.name.includes(query))&&(!status||card.dataset.status===status);card.style.display=show?'':'none';if(show)visible++}});document.querySelector('#visible-count').textContent=`${{visible}}개 표시`}}
document.querySelector('#search')?.addEventListener('input',filterExperiments);document.querySelector('#status-filter')?.addEventListener('change',filterExperiments);if(document.querySelector('#search'))filterExperiments();
async function results(id){{const box=document.querySelector(`#result-${{id}}`);box.classList.remove('hidden');box.innerHTML='<p class="sub">분석 중...</p>';const r=await fetch(`/admin/experiments/${{id}}/results`);if(!r.ok){{box.innerHTML='<p class="notice">결과를 불러오지 못했습니다.</p>';return}}const d=await r.json();const q=d.quality||{{}};const labels={{promotion_button_click:'메뉴 상품 버튼',promotion_quick_reply_click:'스케줄 퀵리플라이',commerce_card_click:'commerceCard 구매 버튼',promotion_click:'기존 클릭',promotion_block_click:'기타 블록'}};const eventCards=(d.event_breakdown||[]).map(e=>`<div class="metric event-metric"><span>${{labels[e.event_name]||e.event_name}}</span><b>${{e.users}}명</b><small>${{e.product_key||'상품 미상'}} · ${{e.events}}건</small></div>`).join('');box.innerHTML=`<div class="result-summary"><div class="metric"><span>배정 사용자</span><b>${{d.assigned_users}}</b></div><div class="metric"><span>전체 이벤트</span><b>${{d.events}}</b></div><div class="metric"><span>샘플 충족</span><b>${{q.sample_size_ok?'예':'아니오'}}</b></div><div class="metric"><span>SRM</span><b>${{d.srm?.status||'-'}}</b></div></div><div class="event-breakdown"><h4>이벤트별 클릭</h4><div class="result-summary">${{eventCards||'<span class="sub">아직 클릭 이벤트가 없습니다.</span>'}}</div></div><table><thead><tr><th>변형</th><th>상품</th><th>노출 사용자</th><th>클릭 사용자</th><th>전환율</th><th>비교 p-value</th></tr></thead><tbody>${{d.variants.map(v=>`<tr><td>${{v.variant_key}}</td><td>${{v.product_key||'-'}}</td><td>${{v.exposed_users}}</td><td>${{v.clicked_users}}</td><td>${{(v.conversion_rate*100).toFixed(2)}}%</td><td>${{v.comparison?(v.comparison.p_value).toFixed(4):'-'}}</td></tr>`).join('')}}</tbody></table>`}}
async function refreshLive(){{for(const card of document.querySelectorAll('.experiment-card[data-status="running"]')){{const id=card.dataset.id;const box=document.querySelector(`#live-${{id}}`);try{{const d=await (await fetch(`/admin/experiments/${{id}}/results`)).json();const min=d.min_sample_size_per_variant||0;const exposed=(d.variants||[]).reduce((n,v)=>n+(v.exposed_users||0),0);const progressExposed=Math.max(...(d.variants||[]).map(v=>v.exposed_users||0),0);const pct=min?Math.min(100,progressExposed/min*100):0;const clicked=(d.variants||[]).reduce((n,v)=>n+(v.clicked_users||0),0);box.innerHTML=`<span class="live-label">실시간 현황</span><b>${{exposed.toLocaleString()}}명 노출</b><span>${{clicked.toLocaleString()}}명 클릭</span><span>CTR ${{(exposed?clicked/exposed*100:0).toFixed(2)}}%</span><span>목표 ${{pct.toFixed(0)}}%</span><i class="progress"><i style="width:${{pct}}%"></i></i><span class="srm">SRM ${{d.srm?.status||'-'}}</span>`}}catch(e){{box.innerHTML='<span class="live-label">실시간 현황</span><span>잠시 후 다시 시도합니다.</span>'}}}}
}}
if(document.querySelector('.experiment-card[data-status="running"]')){{refreshLive();setInterval(refreshLive,30000)}}
</script></body></html>"""
    # The template keeps doubled braces so its CSS/JS can also be embedded safely
    # in the earlier f-string-based version of this page.
    page = page.replace("{{", "{").replace("}}", "}")
    page = page.replace("__PAGE_MODE__", page_mode).replace("__EXPERIMENT_COUNT__", str(experiment_count)).replace("__CARDS__", card_markup)
    return page
