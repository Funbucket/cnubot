import html
import os
import secrets
from typing import Any

from app.services import experiments
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
    experiment_key: str
    name: str
    hypothesis: str
    primary_metric: str
    guardrail_metric: str | None = None
    variants: list[VariantInput] = Field(min_length=2)


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


@router.post("/experiments/{experiment_id}/{status}")
async def change_status(experiment_id: int, status: str, _: str = Depends(require_admin)):
    if status not in {"running", "paused", "completed"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 상태입니다.")
    await experiments.set_experiment_status(experiment_id, status)
    return {"ok": True}


@router.get("/experiments/{experiment_id}/results")
async def results(experiment_id: int, _: str = Depends(require_admin)):
    return await experiments.get_results(experiment_id)


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
<label>실험 키<input name="experiment_key" placeholder="promotion_button_copy_v1" required></label>
<label>실험 이름<input name="name" placeholder="간식 특가 버튼 문구 테스트" required></label>
<label>가설<textarea name="hypothesis" required>상품 중심 문구가 일반 문구보다 클릭률을 높인다.</textarea></label>
<label>핵심 지표<input name="primary_metric" value="promotion_click_rate" required></label>
<label>가드레일 지표<input name="guardrail_metric" value="menu_response_error_rate"></label>
<label>A 변형 키<input name="a_key" value="control"></label><label>A 버튼 문구<input name="a_label" value="간식 특가"></label>
<label>B 변형 키<input name="b_key" value="treatment"></label><label>B 버튼 문구<input name="b_label" value="황치즈 버터링 특가"></label>
<button>실험 초안 만들기</button>
</form>
<h2>실험 목록</h2>{cards or '<p>아직 만든 실험이 없습니다.</p>'}
<script>
const form=document.querySelector('#new-experiment');
form.addEventListener('submit',async(e)=>{{e.preventDefault();const f=new FormData(form);const body={{experiment_key:f.get('experiment_key'),name:f.get('name'),hypothesis:f.get('hypothesis'),primary_metric:f.get('primary_metric'),guardrail_metric:f.get('guardrail_metric'),variants:[{{variant_key:f.get('a_key'),label:f.get('a_label'),weight:50,config:{{button_label:f.get('a_label')}}}},{{variant_key:f.get('b_key'),label:f.get('b_label'),weight:50,config:{{button_label:f.get('b_label')}}}}]}};const r=await fetch('/admin/experiments',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});if(r.ok)location.reload();else alert(await r.text())}});
async function statusChange(id,status){{await fetch(`/admin/experiments/${{id}}/${{status}}`,{{method:'POST'}});location.reload()}}
async function results(id){{const r=await fetch(`/admin/experiments/${{id}}/results`);document.querySelector(`#result-${{id}}`).textContent=JSON.stringify(await r.json(),null,2)}}
</script></html>"""
