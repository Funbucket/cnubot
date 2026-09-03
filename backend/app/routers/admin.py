import html
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


@router.get("/experiments", response_class=HTMLResponse)
async def experiments_home(_: str = Depends(require_admin)):
    rows = await experiments.list_experiments()
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
    return f"""
    <article class="experiment-card" data-name="{html.escape(row['name'].lower())}" data-status="{row['status']}">
      <div class="card-top"><div><span class="eyebrow">{html.escape(row['experiment_key'])}</span><h3>{html.escape(row['name'])}</h3></div><span class="status status-{row['status']}">{status_label}</span></div>
      <p class="hypothesis">{html.escape(row['hypothesis'])}</p>
      <div class="meta-grid"><div><span>핵심 지표</span><b>{html.escape(row['primary_metric'])}</b></div><div><span>가드레일</span><b>{html.escape(row['guardrail_metric'] or '-')}</b></div><div><span>최소 샘플 / 변형</span><b>{sample}명</b></div><div><span>유의수준 · 검정력</span><b>{row.get('alpha', 0.05):.2f} · {row.get('power', 0.8):.0%}</b></div></div>
      <div class="variants"><h4>변형</h4><ul>{variants}</ul></div>
      <div class="actions">{actions}<button class="secondary" onclick="results({experiment_id})">결과 보기</button></div>
      <div id="result-{experiment_id}" class="result-panel hidden"></div>
    </article>
    """


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
 .new-page .page-list{{display:none}}.list-page #new-experiment{{display:none}}nav{{display:flex;gap:8px;margin-bottom:12px}}nav a{{color:#3767e8;text-decoration:none;font-size:13px;font-weight:700;padding:8px 10px;border-radius:8px}}nav a.nav-primary{{background:#3767e8;color:#fff}}
</style>
<body class="__PAGE_MODE__"><main class="shell"><header><div><span class="eyebrow">CNU EXPERIMENT LAB</span><h1>실험실</h1><p class="sub">가설을 검증하고, 학습을 기록하세요.</p></div><div><nav><a href="/admin/experiments">실험 목록</a><a class="nav-primary" href="/admin/experiments/new">＋ 새 실험</a></nav><div class="notice">결정 전 샘플 수와 SRM을 확인하세요.</div></div></header>
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
async function results(id){{const box=document.querySelector(`#result-${{id}}`);box.classList.remove('hidden');box.innerHTML='<p class="sub">분석 중...</p>';const r=await fetch(`/admin/experiments/${{id}}/results`);if(!r.ok){{box.innerHTML='<p class="notice">결과를 불러오지 못했습니다.</p>';return}}const d=await r.json();const q=d.quality||{{}};box.innerHTML=`<div class="result-summary"><div class="metric"><span>배정 사용자</span><b>${{d.assigned_users}}</b></div><div class="metric"><span>이벤트</span><b>${{d.events}}</b></div><div class="metric"><span>샘플 충족</span><b>${{q.sample_size_ok?'예':'아니오'}}</b></div><div class="metric"><span>SRM</span><b>${{d.srm?.status||'-'}}</b></div></div><table><thead><tr><th>변형</th><th>노출 사용자</th><th>클릭 사용자</th><th>전환율</th><th>비교 p-value</th></tr></thead><tbody>${{d.variants.map(v=>`<tr><td>${{v.variant_key}}</td><td>${{v.exposed_users}}</td><td>${{v.clicked_users}}</td><td>${{(v.conversion_rate*100).toFixed(2)}}%</td><td>${{v.comparison?(v.comparison.p_value).toFixed(4):'-'}}</td></tr>`).join('')}}</tbody></table>`}}
</script></body></html>"""
    # The template keeps doubled braces so its CSS/JS can also be embedded safely
    # in the earlier f-string-based version of this page.
    page = page.replace("{{", "{").replace("}}", "}")
    page = page.replace("__PAGE_MODE__", page_mode).replace("__EXPERIMENT_COUNT__", str(experiment_count)).replace("__CARDS__", card_markup)
    return page
