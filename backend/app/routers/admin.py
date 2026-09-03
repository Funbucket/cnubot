import html
import os
import secrets
from typing import Any

from app.services import experiments
from app.services import llm
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
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
    mde: float | None = Field(default=None, gt=0, lt=1)
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
    rows = await experiments.list_experiments()
    cards = "".join(_experiment_card(row) for row in rows)
    return HTMLResponse(_page(cards))


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
    return f"""
    <article class="card">
      <div class="row"><h3>{html.escape(row['name'])}</h3><span class="status">{row['status']}</span></div>
      <p><b>가설:</b> {html.escape(row['hypothesis'])}</p>
      <p><b>핵심 지표:</b> {html.escape(row['primary_metric'])} · <b>가드레일:</b> {html.escape(row['guardrail_metric'] or '-')}</p>
      <ul>{variants}</ul>
      {actions} <button onclick="results({experiment_id})">결과 보기</button>
      <pre id="result-{experiment_id}"></pre>
    </article>
    """


def _page(cards: str) -> str:
    return f"""<!doctype html>
<html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>실험 어드민</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:1000px;margin:32px auto;padding:0 16px;background:#f6f7f9;color:#18202a}}
.card,form{{background:white;border:1px solid #e3e6eb;border-radius:12px;padding:18px;margin:14px 0;box-shadow:0 2px 8px #0000000b}}
input,textarea{{width:100%;box-sizing:border-box;margin:6px 0 12px;padding:9px;border:1px solid #ccd2da;border-radius:6px}}
button{{border:0;border-radius:6px;padding:8px 12px;background:#1769e0;color:white;cursor:pointer;margin:3px}}
.row{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.status{{background:#eef3ff;padding:4px 8px;border-radius:12px;font-size:12px}}
pre{{white-space:pre-wrap;background:#f4f6f8;padding:8px;border-radius:6px}}
</style>
<h1>실험 어드민</h1>
<p>가설을 먼저 기록하고, 변형·핵심 지표·가드레일을 정한 뒤 실험을 시작하세요.</p>
<form id="new-experiment">
<h2>새 실험</h2>
<label>AI에게 설계 요청<textarea id="ai-prompt" placeholder="예: 황치즈 버터링 특가 버튼 문구의 클릭률을 높일 수 있는 A/B 실험을 설계해줘"></textarea></label>
<button type="button" onclick="aiSuggest()">AI 실험 초안 만들기</button>
<label>실험 키<input name="experiment_key" placeholder="비워두면 자동 생성"></label>
<label>실험 이름<input name="name" placeholder="간식 특가 버튼 문구 테스트" required></label>
<label>가설<textarea name="hypothesis" required>상품 중심 문구가 일반 문구보다 클릭률을 높인다.</textarea></label>
<label>핵심 지표<input name="primary_metric" value="promotion_click_rate" required></label>
<label>가드레일 지표<input name="guardrail_metric" value="menu_response_error_rate"></label>
<label>기준 전환율<input name="baseline_rate" type="number" step="0.001" min="0.001" max="0.999" placeholder="예: 0.05"></label>
<label>최소 검출 효과(MDE)<input name="mde" type="number" step="0.001" min="0.001" max="0.999" placeholder="예: 0.01"></label>
<label>유의수준 α<input name="alpha" type="number" step="0.01" value="0.05"></label>
<label>검정력 power<input name="power" type="number" step="0.05" value="0.8"></label>
<label>A 변형 키<input name="a_key" value="control"></label><label>A 버튼 문구<input name="a_label" value="간식 특가"></label>
<label>B 변형 키<input name="b_key" value="treatment"></label><label>B 버튼 문구<input name="b_label" value="황치즈 버터링 특가"></label>
<button>실험 초안 만들기</button>
</form>
<h2>실험 목록</h2>{cards or '<p>아직 만든 실험이 없습니다.</p>'}
<script>
const form=document.querySelector('#new-experiment');
async function aiSuggest(){{const prompt=document.querySelector('#ai-prompt').value;if(!prompt)return alert('AI에게 요청할 내용을 입력하세요.');const r=await fetch('/admin/suggest',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{prompt}})}});if(!r.ok)return alert(await r.text());const d=await r.json();form.name.value=d.name||'';form.hypothesis.value=d.hypothesis||'';form.primary_metric.value=d.primary_metric||'';form.guardrail_metric.value=d.guardrail_metric||'';if(d.variants?.length>=2){{form.a_key.value=d.variants[0].variant_key;form.a_label.value=d.variants[0].label;form.b_key.value=d.variants[1].variant_key;form.b_label.value=d.variants[1].label;}}}}
form.addEventListener('submit',async(e)=>{{e.preventDefault();const f=new FormData(form);const num=(name)=>f.get(name)?Number(f.get(name)):null;const body={{experiment_key:f.get('experiment_key')||null,name:f.get('name'),hypothesis:f.get('hypothesis'),primary_metric:f.get('primary_metric'),guardrail_metric:f.get('guardrail_metric'),alpha:num('alpha'),power:num('power'),baseline_rate:num('baseline_rate'),mde:num('mde'),variants:[{{variant_key:f.get('a_key'),label:f.get('a_label'),weight:50,config:{{button_label:f.get('a_label')}}}},{{variant_key:f.get('b_key'),label:f.get('b_label'),weight:50,config:{{button_label:f.get('b_label')}}}}]}};const r=await fetch('/admin/experiments',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});if(r.ok)location.reload();else alert(await r.text())}});
async function statusChange(id,status){{await fetch(`/admin/experiments/${{id}}/${{status}}`,{{method:'POST'}});location.reload()}}
async function results(id){{const r=await fetch(`/admin/experiments/${{id}}/results`);document.querySelector(`#result-${{id}}`).textContent=JSON.stringify(await r.json(),null,2)}}
</script></html>"""
