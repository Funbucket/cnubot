import html
import asyncio
import os
import secrets
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo
from pathlib import Path

from app.services import experiments
from app.services import llm
from app.services import toss_sharelink
from app.services import promotion_settings
from fastapi import APIRouter, Depends, HTTPException, Query, Header
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
    return RedirectResponse("/admin/recommendations", status_code=303)


@router.get("/recommendations", response_class=HTMLResponse)
async def recommendations(_: str = Depends(require_admin)):
    return HTMLResponse((Path(__file__).parent.parent / "static" / "promotion_editor.html").read_text(),
                        headers={"Cache-Control": "no-store"})


def require_editor(x_promotion_editor: str = Header(default="")):
    if x_promotion_editor != "1":
        raise HTTPException(status_code=403, detail="관리자 상품 편집 화면에서 요청해주세요.")


class ShareTextInput(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@router.get("/promotion-settings")
async def get_promotion_settings(_: str = Depends(require_admin)):
    from fastapi.responses import JSONResponse
    return JSONResponse(promotion_settings.read_settings().model_dump(), headers={"Cache-Control": "no-store"})


@router.put("/promotion-settings", dependencies=[Depends(require_editor)])
async def put_promotion_settings(payload: promotion_settings.Settings, _: str = Depends(require_admin)):
    try:
        return await asyncio.to_thread(promotion_settings.save_settings, payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/promotion-settings/parse", dependencies=[Depends(require_editor)])
async def parse_promotion(payload: ShareTextInput, _: str = Depends(require_admin)):
    try:
        product = promotion_settings.parse_share_text(payload.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    warning = ""
    try:
        product = await asyncio.to_thread(promotion_settings.enrich_product, product)
    except Exception:
        warning = "이미지 자동 조회에 실패했습니다. 상품명과 링크는 등록되며 이미지는 직접 입력할 수 있습니다."
    return {"product": product.model_dump(), "warning": warning}


@router.post("/promotion-settings/preview", dependencies=[Depends(require_editor)])
async def preview_promotions(payload: promotion_settings.Settings, refresh: bool = False,
                             _: str = Depends(require_admin)):
    from app.services import promotions
    pairs = await promotion_settings.resolved_fixed_products(payload, force=refresh)
    return {"response": promotions.create_toss_shopping_list_response([p for _, p in pairs]),
            "warnings": [{"title": p["title"], "message": p["price_error"]}
                         for _, p in pairs if p.get("price_error")],
            "checked_at": [p.get("price_checked_at") for _, p in pairs]}


@router.get("/insights", response_class=HTMLResponse)
async def insights(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    all_time: bool = Query(default=False),
    _: str = Depends(require_admin),
):
    if not all_time and start_date is None and end_date is None:
        end_date = datetime.now(ZoneInfo("Asia/Seoul")).date()
        start_date = end_date - timedelta(days=29)
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="시작일은 종료일보다 빠를 수 없습니다.")
    data = await experiments.get_promotion_insights(start_date, end_date)
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


def _recommendations_page(products: list[dict[str, Any]], error: str = "") -> str:
    rows = "".join(
        f"<tr><td>{index}</td><td>{html.escape(str(item.get('displayName', '-')))}</td>"
        f"<td>{item.get('displayPrice', 0):,}원</td><td>{'품절' if item.get('isSoldOut') else '판매 중'}</td></tr>"
        for index, item in enumerate(products, 1)
    ) or '<tr><td colspan="4">상품 목록이 없습니다.</td></tr>'
    notice = f'<div class="warning">{html.escape(error)}</div>' if error else ""
    return f"""<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>CNU 개인화 추천</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f5f7fb;color:#172033;margin:0}}
main{{max-width:900px;margin:auto;padding:32px 20px 64px}}
header{{display:flex;justify-content:space-between;align-items:end;gap:20px;margin-bottom:24px}}
h1{{margin:4px 0 8px;font-size:30px}}h2{{margin:28px 0 12px;font-size:19px}}
.sub{{color:#68738a;line-height:1.6}}nav{{display:flex;gap:8px;flex-wrap:wrap}}
nav a{{color:#3767e8;text-decoration:none;font-weight:700;font-size:13px}}
.card{{background:#fff;border:1px solid #e3e8f0;border-radius:16px;padding:22px;margin:14px 0}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.metric{{background:#f7f9fc;border-radius:10px;padding:14px}}
.metric span{{display:block;color:#71809b;font-size:12px;margin-bottom:6px}}.metric b{{font-size:16px}}
.status{{color:#147342;background:#dcf8e8;border-radius:99px;padding:6px 10px;font-size:12px;font-weight:700}}
.warning{{background:#fff8e7;border:1px solid #f3dfaa;border-radius:10px;padding:12px;color:#785b12}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;padding:10px;border-bottom:1px solid #edf0f5}}th{{color:#71809b}}
code{{background:#f1f4fa;padding:2px 5px;border-radius:5px}}@media(max-width:650px){{header{{display:block}}.grid{{grid-template-columns:1fr}}nav{{margin-top:16px}}}}
</style><main><header><div><div class="sub">CNU RECOMMENDATION CENTER</div><h1>개인화 추천</h1><p class="sub">사용자별 클릭 카테고리를 학습해 Toss 인기상품 순위를 개인화합니다.</p></div><nav><a href="/admin/recommendations">개인화 추천</a><a href="/admin/experiments">보관된 실험</a><a href="/admin/insights">기존 인사이트</a></nav></header>
{notice}<section class="card"><div class="grid"><div class="metric"><span>운영 상태</span><b class="status">개인화 추천 운영 중</b></div><div class="metric"><span>추천 정책</span><b>인기상품 + 카테고리 affinity</b></div><div class="metric"><span>상품 캐시</span><b>1시간</b></div></div><p class="sub">사용자가 클릭한 상품의 카테고리 점수를 저장하고, 이후 같은 카테고리의 Toss 인기상품을 우선 추천합니다. 신규 사용자는 전체 인기순으로 시작하며 API 오류 시 fallback 상품을 사용합니다.</p></section>
<section class="card"><h2>현재 후보 상품</h2><table><thead><tr><th>순위</th><th>상품</th><th>가격</th><th>상태</th></tr></thead><tbody>{rows}</tbody></table></section></main></html>"""


def _insights_page(data: dict[str, Any]) -> str:
    totals = data["totals"]
    paths = data.get("paths", [])
    by_path = {item["path"]: item for item in paths}
    entry_path = by_path.get("entry", {})
    inline_path = by_path.get("inline", {})
    all_clicked = sum(item["clicked_users"] for item in paths)
    all_reach = sum(item["reach_users"] for item in paths)
    path_rows = _insight_path_rows(paths)
    fatigue_rows = _insight_fatigue_rows(data.get("fatigue", []))
    guardrail_rows = _insight_guardrail_rows(data.get("guardrails", []))
    path_funnels = _insight_path_funnels(paths, totals)
    entry_reach = entry_path.get("reach_users") or 0
    entry_reach_events = entry_path.get("reach_events") or 0
    entry_action_rate = entry_path.get("action_rate") or 0
    entry_click_rate = entry_path.get("click_rate") or 0
    inline_reach = inline_path.get("reach_users") or 0
    inline_reach_events = inline_path.get("reach_events") or 0
    inline_click_rate = inline_path.get("click_rate") or 0
    exposed = totals.get("exposed_users") or 0
    clicked = totals.get("clicked_users") or 0
    entry_exposed_users = totals.get("entry_exposed_users") or 0
    entry_exposure_events = totals.get("entry_exposure_events") or 0
    entry_users = totals.get("entry_users") or 0
    entry_events = totals.get("entry_events") or 0
    exposure_events = totals.get("exposure_events") or 0
    click_events = totals.get("click_events") or 0
    ctr = clicked / exposed * 100 if exposed else 0
    entry_ctr = entry_users / entry_exposed_users * 100 if entry_exposed_users else 0
    exposure_after_entry = exposed / entry_users * 100 if entry_users else 0
    data_status = "수집 중" if entry_exposure_events or entry_events or exposure_events or click_events else "데이터 대기 중"
    product_rows = "".join(
        f"<tr><td><b style=\"font-size:14px\">{html.escape(row.get('product_name') or _insight_label(row['product_key']))}</b>"
        f"<span style=\"display:block;margin-top:5px;color:#71809b;font-size:11px;line-height:1.45\">"
        f"카테고리 · {html.escape(row.get('category_name') or '미상')}</span>"
        f"<small><code>{html.escape(row['product_key'])}</code></small></td>"
        f"<td data-label=\"노출\">{row['exposed_users']:,}</td><td data-label=\"클릭\">{row['clicked_users']:,}</td>"
        f"<td data-label=\"CTR\"><b>{(row['clicked_users'] / row['exposed_users'] * 100 if row['exposed_users'] else 0):.2f}%</b></td>"
        f"<td data-label=\"최종 클릭\"><b style=\"color:#147342\">{_insight_surfaces(row.get('click_surfaces'))}</b><small>{row['click_events']:,}건</small></td></tr>"
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
    message_rows = "".join(
        f"<tr><td><b>{html.escape(row['label'])}</b><small>{html.escape(_insight_sources(row.get('source')))}</small></td>"
        f"<td data-label=\"버튼 노출\">{row['exposed_users']:,}명</td>"
        f"<td data-label=\"버튼 클릭\">{row['entry_users']:,}명</td>"
        f"<td data-label=\"버튼 CTR\"><b>{(row['entry_users'] / row['exposed_users'] * 100 if row['exposed_users'] else 0):.2f}%</b></td>"
        f"<td data-label=\"상품 클릭\">{row['card_clicked_users']:,}명</td>"
        f"<td data-label=\"상품 CTR\"><b>{(row['card_clicked_users'] / row['entry_users'] * 100 if row['entry_users'] else 0):.2f}%</b></td></tr>"
        for row in data.get("entry_labels", [])
    ) or '<tr><td colspan="6" class="sub">문구별 버튼 노출 데이터가 아직 없습니다.</td></tr>'
    position_rows = "".join(
        f"<div class=\"position-cell\"><b>{row['row']}행 {row['column']}열</b>"
        f"<strong>{(row['clicked_users'] / row['exposed_users'] * 100 if row['exposed_users'] else 0):.2f}%</strong>"
        f"<small>노출 사용자 {row['exposed_users']:,}명 · 클릭 사용자 {row['clicked_users']:,}명</small>"
        f"<small>노출 이벤트 {row['exposed_events']:,}회 · 클릭 이벤트 {row['click_events']:,}건</small></div>"
        for row in data.get("positions", [])
    ) or '<div class="sub">위치가 기록된 commerceCard 데이터가 아직 없습니다. 배포 후부터 집계됩니다.</div>'
    daily_rows = "".join(
        f"<tr><td data-label=\"날짜\">{html.escape(str(row['day']))}</td><td data-label=\"노출\">{row['exposed_users']:,}명</td>"
        f"<td data-label=\"클릭 사용자\">{row['clicked_users']:,}명</td><td data-label=\"클릭 이벤트\">{row['click_events']:,}건</td></tr>"
        for row in data["daily"]
    ) or '<tr><td colspan="4" class="sub">아직 일별 데이터가 없습니다.</td></tr>'
    path_sql = """WITH events AS (
  SELECT user_id, event_name, created_at,
         CASE WHEN surface = 'menu_inline_card' THEN 'inline' ELSE 'entry' END AS path
  FROM qualified_promotion_events
)
SELECT path,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_entry_exposure') AS entry_exposed_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_entry_click') AS entry_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure') AS exposed_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name IN ('promotion_click', 'promotion_button_click', 'promotion_quick_reply_click', 'promotion_block_click', 'commerce_card_click')) AS clicked_users
FROM events GROUP BY path;"""
    guardrail_sql = """WITH visit_events AS (
  SELECT user_id, event_name, (created_at AT TIME ZONE 'Asia/Seoul')::date AS day
  FROM user_events
  WHERE user_id IS NOT NULL
    AND event_name IN ('menu_view', 'promotion_entry_exposure', 'promotion_exposure')
), visits AS (SELECT DISTINCT user_id, day FROM visit_events
), menu_views AS (
  SELECT day, user_id, COUNT(*) AS views FROM visit_events
  WHERE event_name = 'menu_view' GROUP BY day, user_id
)
SELECT v.day, COUNT(DISTINCT v.user_id) AS active_users,
  COUNT(DISTINCT v.user_id) FILTER (WHERE EXISTS (
    SELECT 1 FROM visits n WHERE n.user_id = v.user_id AND n.day = v.day + 1)) AS returned_users,
  COALESCE(SUM(m.views), 0) AS menu_views
FROM visits v LEFT JOIN menu_views m ON m.user_id = v.user_id AND m.day = v.day
GROUP BY v.day ORDER BY v.day DESC;"""
    fatigue_sql = """WITH events AS (
  SELECT user_id, event_name, created_at,
         CASE WHEN surface = 'menu_inline_card' THEN 'inline' ELSE 'entry' END AS path
  FROM qualified_promotion_events
), impressions AS (
  SELECT user_id, path, created_at,
         ROW_NUMBER() OVER (PARTITION BY user_id, path ORDER BY created_at) AS nth,
         LEAD(created_at) OVER (PARTITION BY user_id, path ORDER BY created_at) AS next_at
  FROM events
  WHERE (path = 'entry' AND event_name = 'promotion_entry_exposure')
     OR (path = 'inline' AND event_name = 'promotion_exposure')
), actions AS (
  SELECT user_id, path, created_at FROM events
  WHERE (path = 'entry' AND event_name = 'promotion_entry_click')
     OR (path = 'inline' AND event_name = 'commerce_card_click')
)
SELECT path, LEAST(nth, 6) AS nth, COUNT(*) AS impressions,
  COUNT(*) FILTER (WHERE EXISTS (
    SELECT 1 FROM actions a WHERE a.user_id = impressions.user_id AND a.path = impressions.path
      AND a.created_at >= impressions.created_at
      AND (impressions.next_at IS NULL OR a.created_at < impressions.next_at))) AS actions
FROM impressions GROUP BY 1, 2 ORDER BY 1, 2;"""
    product_sql = """WITH normalized AS (
  SELECT COALESCE(e.product_key, e.properties->>'product_key', v.config->>'product_key', 'unknown') AS product_key,
         e.user_id, e.event_name
  FROM user_events e
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
FROM user_events
WHERE event_name IN ('promotion_button_click', 'promotion_quick_reply_click', 'commerce_card_click')
GROUP BY 1;"""
    daily_sql = """SELECT (created_at AT TIME ZONE 'Asia/Seoul')::date AS day,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure') AS exposed_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name IN ('promotion_click', 'promotion_button_click', 'promotion_quick_reply_click', 'promotion_block_click', 'commerce_card_click')) AS clicked_users
FROM user_events
GROUP BY day ORDER BY day DESC LIMIT 30;"""
    button_sql = """SELECT
  COALESCE(properties->>'button_label', properties->>'entry_button_label') AS button_label,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_entry_exposure') AS exposed_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_entry_click') AS clicked_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'commerce_card_click') AS product_clicked_users
FROM qualified_promotion_events
WHERE event_name IN ('promotion_entry_exposure', 'promotion_entry_click', 'commerce_card_click')
GROUP BY 1 ORDER BY exposed_users DESC;"""
    position_sql = """SELECT (properties->>'position')::int AS position,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure') AS exposed_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'commerce_card_click') AS clicked_users
FROM qualified_promotion_events
WHERE event_name IN ('promotion_exposure', 'commerce_card_click')
GROUP BY 1 ORDER BY position;"""
    start_value = html.escape(str(data.get("start_date") or ""))
    end_value = html.escape(str(data.get("end_date") or ""))
    summary_sql = """SELECT
  COUNT(DISTINCT user_id) FILTER (WHERE event_name = 'promotion_exposure') AS exposed_users,
  COUNT(DISTINCT user_id) FILTER (WHERE event_name IN ('promotion_click', 'promotion_button_click', 'promotion_quick_reply_click', 'promotion_block_click', 'commerce_card_click')) AS clicked_users
FROM user_events
WHERE created_at >= :start_date AND created_at < (:end_date + INTERVAL '1 day');"""
    def details(query: str) -> str:
        return (
            '<details><summary>SQL 펼쳐보기</summary>'
            f'<pre style="white-space:pre;overflow:auto;max-height:360px">{html.escape(query)}</pre></details>'
        )
    page = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CNU 인사이트</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#f6f8fc;color:#14213d;font-family:Inter,system-ui,sans-serif}}.shell{{max-width:1180px;margin:auto;padding:30px 22px 72px}}header{{display:flex;justify-content:space-between;align-items:end;gap:24px;margin-bottom:24px}}h1{{font-size:30px;letter-spacing:-.045em;margin:5px 0 8px}}h2{{font-size:18px;letter-spacing:-.025em;margin:30px 0 10px}}.sub,.hint{{color:#71809b}}.sub{{line-height:1.5;margin:0}}.eyebrow{{font:700 11px ui-monospace,monospace;color:#6680b8;letter-spacing:.08em}}nav{{display:flex;gap:6px;flex-wrap:wrap}}nav a{{padding:9px 11px;border-radius:9px;color:#5270aa;text-decoration:none;font-size:13px;font-weight:700}}nav a.active{{background:#e9efff;color:#315dcc}}.filters,.hero,.card,.funnel{{border:1px solid #e3e9f3;border-radius:18px;background:#fff;box-shadow:0 10px 30px #1b31500b}}.filters{{display:flex;align-items:end;gap:10px;padding:14px;margin-bottom:16px}}.filters label{{display:block;color:#71809b;font-size:11px;margin-bottom:5px}}.filters input{{font:inherit;border:1px solid #d7deea;border-radius:9px;padding:9px 10px;color:#14213d}}.filters button{{border:0;border-radius:9px;padding:10px 15px;background:#315dcc;color:#fff;font-weight:800;cursor:pointer}}.filters a{{padding:10px 4px;color:#315dcc;font-size:12px;text-decoration:none;white-space:nowrap}}.tilde{{color:#9aa6b9;padding-bottom:10px}}.hero{{background:linear-gradient(135deg,#233d91,#315dcc 65%,#6688f2);color:#fff;padding:25px;margin-bottom:16px}}.hero .eyebrow,.hero .sub{{color:#dce6ff}}.hero-row{{display:flex;justify-content:space-between;align-items:end;gap:20px}}.hero h1{{margin-top:7px}}.live{{padding:9px 12px;border:1px solid #ffffff40;border-radius:99px;background:#ffffff1c;font-size:12px;font-weight:800;white-space:nowrap}}.live i{{display:inline-block;width:7px;height:7px;border-radius:50%;background:#7dffb2;margin-right:6px}}.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}}.card{{padding:17px}}.kpi-label{{font-size:12px;color:#71809b}}.kpi-value{{font-size:25px;font-weight:850;letter-spacing:-.05em;margin:8px 0 3px}}.kpi-note{{font-size:11px;color:#8b98ac}}.funnel{{padding:19px;margin-top:16px}}.section-head{{display:flex;justify-content:space-between;align-items:end;gap:16px}}.section-head h2{{margin:0}}.funnel-track{{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;margin-top:16px}}.funnel-step{{position:relative;background:#f3f6ff;border-radius:13px;padding:14px;min-height:118px}}.funnel-step:not(:last-child)::after{{content:'›';position:absolute;right:-8px;top:43px;color:#9aace0;font-size:25px;font-weight:800;z-index:1}}.funnel-step strong{{display:block;color:#315dcc;font-size:11px}}.funnel-step b{{display:block;font-size:25px;letter-spacing:-.05em;margin:8px 0 4px}}.funnel-step small{{display:block;color:#71809b;font-size:11px;line-height:1.45}}.layout{{display:grid;grid-template-columns:1.35fr 1fr;gap:14px}}.panel{{padding:18px;border:1px solid #e3e9f3;border-radius:16px;background:#fff;box-shadow:0 10px 30px #1b31500b;overflow:hidden}}.panel h2{{margin:0}}.panel-head{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:10px}}.scroll{{max-height:390px;overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th,td{{padding:12px 8px;text-align:left;border-bottom:1px solid #edf0f5;white-space:nowrap}}th{{font-size:11px;color:#71809b;font-weight:750}}td small{{display:block;color:#8a96a8;font-size:11px;margin-top:3px}}code{{font-size:11px;color:#71809b}}.two{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.position-grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}.position-cell{{background:#f4f7ff;border:1px solid #e1e8ff;border-radius:12px;padding:14px;min-height:108px}}.position-cell b,.position-cell strong,.position-cell small{{display:block}}.position-cell b{{color:#315dcc;font-size:12px}}.position-cell strong{{font-size:22px;margin:8px 0 5px}}.position-cell small{{color:#71809b;font-size:11px;line-height:1.5}}details{{margin-top:12px;border-top:1px solid #edf0f5;padding-top:10px}}summary{{cursor:pointer;color:#315dcc;font-size:12px;font-weight:750}}pre{{white-space:pre-wrap;word-break:break-word;background:#f7f9fc;color:#536078;border-radius:9px;padding:12px;font:11px/1.55 ui-monospace,monospace}}
@media(max-width:900px){{.kpis{{grid-template-columns:repeat(3,1fr)}}.funnel-track{{grid-template-columns:repeat(3,1fr)}}.funnel-step:not(:last-child)::after{{display:none}}.layout,.two{{grid-template-columns:1fr}}}}
@media(max-width:620px){{.shell{{padding:20px 14px 48px}}header{{display:block}}nav{{margin-top:16px}}h1{{font-size:26px}}.filters{{display:grid;grid-template-columns:1fr 20px 1fr}}.filters button,.filters a{{grid-column:1/-1;text-align:center}}.kpis,.funnel-track{{grid-template-columns:1fr}}.hero-row,.section-head{{display:block}}.live{{display:inline-block;margin-top:18px}}.funnel-step{{min-height:auto}}table,thead,tbody,tr,td{{display:block}}thead{{display:none}}tr{{padding:9px 0;border-bottom:1px solid #edf0f5}}td{{display:flex;justify-content:space-between;gap:14px;padding:7px 2px;border:0;white-space:normal;text-align:right}}td::before{{content:attr(data-label);color:#71809b;text-align:left}}td:first-child{{display:block;text-align:left;font-size:14px;padding-top:5px}}td:first-child::before{{display:none}}}}
</style></head><body><main class="shell"><header><div><span class="eyebrow">CNU / PROMOTION INTELLIGENCE</span><h1>프로모션 인사이트</h1><p class="sub">사용자가 버튼을 본 순간부터 상품을 클릭하기까지의 흐름을 확인합니다.</p></div><nav><a href="/admin/recommendations">상품·버튼 관리</a><a class="active" href="/admin/insights">인사이트</a><a href="/admin/experiments">실험 목록</a><a href="/admin/experiments/new">＋ 새 실험</a></nav></header>
<form class="filters" method="get" action="/admin/insights"><div><label for="start_date">시작일</label><input id="start_date" name="start_date" type="date" value="{start_value}"></div><span class="tilde">~</span><div><label for="end_date">종료일</label><input id="end_date" name="end_date" type="date" value="{end_value}"></div><button type="submit">기간 적용</button><a href="/admin/insights?all_time=true">전체 기간 보기</a></form>
<section class="hero"><div class="hero-row"><div><span class="eyebrow">DECISION DASHBOARD</span><h1>어디서 사용자가 이탈하는가?</h1><p class="sub">순차 코호트 기준 · 관리자 및 테스트 사용자 제외 · {start_value or '전체'} ~ {end_value or '현재'}</p></div><span class="live"><i></i>{data_status}</span></div></section>
<section class="kpis"><div class="card"><span class="kpi-label">진입형 접점 노출</span><div class="kpi-value">{entry_reach:,}명</div><span class="kpi-note">{entry_reach_events:,}회 · 버튼 CTR {entry_action_rate:.2f}%</span></div><div class="card"><span class="kpi-label">진입형 최종 CTR</span><div class="kpi-value">{entry_click_rate:.2f}%</div><span class="kpi-note">버튼 본 사람 → 상품 클릭</span></div><div class="card"><span class="kpi-label">인라인형 카드 노출</span><div class="kpi-value">{inline_reach:,}명</div><span class="kpi-note">{inline_reach_events:,}회 · 진입 클릭 없음</span></div><div class="card"><span class="kpi-label">인라인형 최종 CTR</span><div class="kpi-value">{inline_click_rate:.2f}%</div><span class="kpi-note">카드 본 사람 → 상품 클릭</span></div><div class="card"><span class="kpi-label">상품 클릭 사용자</span><div class="kpi-value">{all_clicked:,}명</div><span class="kpi-note">두 경로 합계 · 접점 {all_reach:,}명</span></div></section>
<section class="funnel"><div class="section-head"><h2>경로별 사용자 퍼널</h2><span class="hint">각 단계는 이전 단계를 통과한 사용자 기준 · 경로마다 단계 수가 다릅니다</span></div>{path_funnels}{details(summary_sql)}</section><section class="panel"><div class="panel-head"><h2>경로 비교</h2><span class="hint">접점을 본 사람 기준 · 기간 내 고유 사용자(순차 코호트 아님)</span></div><div class="scroll"><table><thead><tr><th>경로</th><th>접점 노출</th><th>1인당 노출</th><th>반응</th><th>상품 클릭</th><th>최종 CTR</th></tr></thead><tbody>{path_rows}</tbody></table></div>{details(path_sql)}</section><section class="panel"><div class="panel-head"><h2>가드레일 · 학식 경험</h2><span class="hint">광고가 붙은 응답만이 아니라 학식 사용 전체 기준 · 나빠지면 광고를 줄여야 합니다</span></div><div class="scroll"><table><thead><tr><th>날짜</th><th>활성 사용자</th><th>1인당 학식 조회</th><th>다음날 재방문</th></tr></thead><tbody>{guardrail_rows}</tbody></table></div>{details(guardrail_sql)}</section><section class="panel"><div class="panel-head"><h2>노출 피로도</h2><span class="hint">같은 사람에게 반복 노출될수록 반응률이 어떻게 변하는가</span></div><div class="scroll"><table><thead><tr><th>경로</th><th>노출 회차</th><th>노출</th><th>반응</th><th>반응률</th></tr></thead><tbody>{fatigue_rows}</tbody></table></div>{details(fatigue_sql)}</section>
<h2>무엇이 성과를 만들었나</h2><p class="sub">기간은 한국 시간 기준입니다. 아래 상세 표는 기간 내 전체 이벤트의 고유 사용자 수이며, 위 요약은 같은 기간 안에 순서대로 진입한 사용자만 집계합니다. 버튼·상품 노출은 응답에 포함된 횟수로, 실제 화면 열람을 보장하지 않습니다. 문구별 노출 시간대가 달라 CTR 차이만으로 문구의 우열을 단정할 수 없습니다.</p><section class="layout"><section class="panel"><div class="panel-head"><h2>상품별 성과</h2><span class="hint">노출·클릭·CTR</span></div><div class="scroll"><table><thead><tr><th>상품</th><th>노출</th><th>클릭</th><th>CTR</th><th>주요 접점</th></tr></thead><tbody>{product_rows}</tbody></table></div>{details(product_sql)}</section><section class="panel"><div class="panel-head"><h2>버튼 문구 성과</h2><span class="hint">버튼 노출 → 버튼 클릭 → 상품 클릭</span></div><div class="scroll"><table><thead><tr><th>문구</th><th>버튼 노출</th><th>버튼 클릭</th><th>버튼 CTR</th><th>상품 클릭</th><th>상품 CTR</th></tr></thead><tbody>{message_rows}</tbody></table></div>{details(button_sql)}</section></section>
<section class="panel"><div class="panel-head"><h2>최근 추이</h2><span class="hint">KST · 최근 30일</span></div><div class="scroll"><table><thead><tr><th>날짜</th><th>노출</th><th>클릭 사용자</th><th>클릭 이벤트</th></tr></thead><tbody>{daily_rows}</tbody></table></div>{details(daily_sql)}</section>
<h2>상품 카드 위치 효과</h2><section class="panel"><div class="panel-head"><h2>어느 위치가 강한가?</h2><span class="hint">commerceCard 순서별 클릭률</span></div><div class="position-grid">{position_rows}</div>{details(position_sql)}</section>
</main></body></html>"""
    return page


def _percent(numerator: int, denominator: int) -> float:
    return numerator / denominator * 100 if denominator else 0.0


PATH_LABELS = {
    "entry": ("진입형", "버튼·퀵리플라이를 눌러 상품 목록으로 이동"),
    "inline": ("인라인형", "학식 응답 안에서 상품 카드를 바로 노출"),
}


def _insight_path_rows(paths: list[dict[str, Any]]) -> str:
    rows = []
    for path in paths:
        name, note = PATH_LABELS.get(path["path"], (path["path"], ""))
        rows.append(
            f"<tr><td><b style=\"font-size:14px\">{html.escape(name)}</b>"
            f"<span style=\"display:block;margin-top:5px;color:#71809b;font-size:11px;line-height:1.45\">{html.escape(note)}</span></td>"
            f"<td data-label=\"접점 노출\">{path['reach_users']:,}명<small>{path['reach_events']:,}회</small></td>"
            f"<td data-label=\"1인당 노출\">{path['impressions_per_user']:.2f}회</td>"
            f"<td data-label=\"반응\">{path['action_users']:,}명<small>{path['action_rate']:.2f}%</small></td>"
            f"<td data-label=\"상품 클릭\"><b>{path['clicked_users']:,}명</b><small>{path['click_events']:,}건</small></td>"
            f"<td data-label=\"최종 CTR\"><b style=\"color:#147342\">{path['click_rate']:.2f}%</b>"
            f"<small>노출당 {path['impression_click_rate']:.2f}%</small></td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="6" class="sub">아직 경로별 데이터가 없습니다.</td></tr>'


def _insight_guardrail_rows(guardrails: list[dict[str, Any]]) -> str:
    rows = []
    for item in guardrails:
        if item["return_rate_pending"]:
            retention = '<span class="sub">집계 중</span>'
        elif not item["return_rate_measurable"]:
            retention = '<span class="sub">측정 불가</span>'
        else:
            retention = f"<b>{item['return_rate']:.2f}%</b><small>{item['returned_users']:,}명 복귀</small>"
        views = (
            f"{item['views_per_user']:.2f}회<small>{item['menu_views']:,}회 / {item['menu_view_users']:,}명</small>"
            if item["menu_view_users"]
            else '<span class="sub">계측 전</span>'
        )
        rows.append(
            f"<tr><td data-label=\"날짜\">{html.escape(str(item['day']))}</td>"
            f"<td data-label=\"활성 사용자\">{item['active_users']:,}명</td>"
            f"<td data-label=\"1인당 학식 조회\">{views}</td>"
            f"<td data-label=\"다음날 재방문\">{retention}</td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="4" class="sub">아직 가드레일 데이터가 없습니다.</td></tr>'


def _insight_fatigue_rows(fatigue: list[dict[str, Any]]) -> str:
    rows = []
    for item in fatigue:
        name = PATH_LABELS.get(item["path"], (item["path"], ""))[0]
        rate = item["actions"] / item["impressions"] * 100 if item["impressions"] else 0
        nth = f"{item['nth']}회차" + ("+" if item["nth"] >= 6 else "")
        rows.append(
            f"<tr><td data-label=\"경로\">{html.escape(name)}</td>"
            f"<td data-label=\"노출 회차\">{nth}</td>"
            f"<td data-label=\"노출\">{item['impressions']:,}회</td>"
            f"<td data-label=\"반응\">{item['actions']:,}건</td>"
            f"<td data-label=\"반응률\"><b>{rate:.2f}%</b></td></tr>"
        )
    return "".join(rows) or '<tr><td colspan="5" class="sub">반복 노출 데이터가 아직 없습니다.</td></tr>'


def _insight_path_funnels(paths: list[dict[str, Any]], totals: dict[str, Any]) -> str:
    """Draw one funnel per path.

    진입형은 단계 순서를 지킨 코호트(totals)를 써야 뒷단계가 앞단계보다 커지지 않는다.
    """
    blocks = []
    for path in paths:
        name, note = PATH_LABELS.get(path["path"], (path["path"], ""))
        if path["path"] == "inline":
            steps = [
                ("01 · 카드 노출", f"{path['reach_users']:,}", f"{path['reach_events']:,}회 · 학식 응답에 카드가 포함됨"),
                ("02 · 상품 클릭", f"{path['clicked_users']:,}", f"{path['click_rate']:.2f}% 전환 · {path['click_events']:,}회"),
            ]
        else:
            entry_exposed = totals.get("entry_exposed_users") or 0
            entry_users = totals.get("entry_users") or 0
            exposed = totals.get("exposed_users") or 0
            clicked = totals.get("clicked_users") or 0
            steps = [
                ("01 · 버튼 노출", f"{entry_exposed:,}", f"{totals.get('entry_exposure_events') or 0:,}회 · 진입점에 버튼이 표시됨"),
                ("02 · 버튼 클릭", f"{entry_users:,}", f"{_percent(entry_users, entry_exposed):.2f}% 전환"),
                ("03 · 상품 노출", f"{exposed:,}", f"{_percent(exposed, entry_users):.2f}% 도달"),
                ("04 · 상품 클릭", f"{clicked:,}", f"{_percent(clicked, exposed):.2f}% 전환 · {totals.get('click_events') or 0:,}회"),
            ]
        cards = "".join(
            f"<div class=\"funnel-step\"><strong>{title}</strong><b>{value}</b><small>{html.escape(hint)}</small></div>"
            for title, value, hint in steps
        )
        blocks.append(
            f"<div class=\"section-head\"><h2>{html.escape(name)} 퍼널</h2>"
            f"<span class=\"hint\">{html.escape(note)}</span></div>"
            f"<div class=\"funnel-track\">{cards}</div>"
        )
    return "".join(blocks) or '<p class="sub">아직 퍼널을 그릴 데이터가 없습니다.</p>'


def _insight_label(product_key: str) -> str:
    return {
        "yellow_cheese_buttering": "황치즈 버터링",
        "lactofit_gold": "락토핏 골드",
        "lavender_wipes": "리벤스 라벤더 물티슈",
        "cento_toothbrush": "센토 프라임 칫솔",
        "unknown": "상품 미상",
    }.get(product_key, product_key)


def _insight_sources(sources: str | None) -> str:
    labels = {
        "quick_reply": "퀵리플라이",
        "menu_card": "식단 메뉴 버튼",
        "promotion_button": "식단 메뉴 버튼",
        "menu_card": "식단 메뉴 버튼",
        "menu_button": "식단 메뉴 버튼",
        "promotion_list": "기존 데이터(경로 미상)",
        "commerce_card": "commerceCard",
    }
    values = [value.strip() for value in (sources or "").split(",") if value.strip()]
    return ", ".join(labels.get(value, value) for value in values) or "유입 경로 미상"


def _insight_entry_label(row: dict[str, Any]) -> str:
    button_label = (row.get("entry_button_label") or "").strip()
    source = _insight_sources(row.get("entry_sources"))
    if button_label and button_label != "unknown":
        return f"{html.escape(button_label)} <span style=\"color:#71809b\">({html.escape(source)})</span>"
    return source


def _insight_entry_button_label(row: dict[str, Any]) -> str:
    label = (row.get("entry_button_label") or "").strip()
    return html.escape(label if label and label != "unknown" else "버튼명 미상")


def _insight_surfaces(surfaces: str | None) -> str:
    labels = {
        "commerce_card": "commerceCard",
    }
    values = [value.strip() for value in (surfaces or "").split(",") if value.strip()]
    return ", ".join(labels.get(value, value) for value in values) or "commerceCard"


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
