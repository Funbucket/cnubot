import asyncio
import os
import secrets
import time

from app.services import experiments
from app.services import llm
from app.services import toss_sharelink
from app.services import promotion_settings
from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.schemas.admin import VariantInput, ExperimentInput, SuggestInput, ShareTextInput


router = APIRouter()
security = HTTPBasic()


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










def require_editor(x_promotion_editor: str = Header(default="")):
    if x_promotion_editor != "1":
        raise HTTPException(status_code=403, detail="관리자 상품 편집 화면에서 요청해주세요.")


@router.get("/promotion-settings")
async def get_promotion_settings(_: str = Depends(require_admin)):
    from fastapi.responses import JSONResponse
    return JSONResponse(promotion_settings.read_settings().model_dump(), headers={"Cache-Control": "no-store"})


@router.get("/promotion-settings/collection-status")
async def product_collection_status(_: str = Depends(require_admin)):
    from fastapi.responses import JSONResponse
    from app.services.product_collection_status import summary
    return JSONResponse(await asyncio.to_thread(summary), headers={"Cache-Control": "no-store"})


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
                             collection_id: str = "living",
                             _: str = Depends(require_admin)):
    from app.services import promotions
    if collection_id == "today_deals":
        pairs = await promotions.get_today_deal_products(record_exposure=False, limit=6)
        return {"response": promotions.create_toss_shopping_list_response(
                    [p for _, p in pairs], collection_id="today_deals"),
                "warnings": [], "checked_at": []}
    collection = payload.collections.get(collection_id) if payload.collections else None
    collection = collection or promotion_settings.read_collection(collection_id)
    preview_settings = promotion_settings.Settings(mode=collection.mode, products=collection.products,
                                                   revision=payload.revision)
    pairs = await promotion_settings.resolved_fixed_products(preview_settings, force=refresh)
    return {"response": promotions.create_toss_shopping_list_response(
                [p for _, p in pairs], collection_id=collection_id),
            "warnings": [{"title": p["title"], "message": p["price_error"]}
                         for _, p in pairs if p.get("price_error")],
            "checked_at": [p.get("price_checked_at") for _, p in pairs]}


@router.get("/promotion-settings/diagnostic")
async def recommendation_diagnostic(collection_id: str = "food", _: str = Depends(require_admin)):
    from app.services import promotions
    from fastapi.responses import JSONResponse
    if collection_id not in {"food", "living"}:
        raise HTTPException(status_code=400, detail="지원하지 않는 기획전입니다.")
    pairs = await promotions.get_live_toss_products(
        collection_id=collection_id, limit=6, record_exposure=False, force_algorithm=True)
    return JSONResponse({
        "response": promotions.create_toss_shopping_list_response([p for _, p in pairs], collection_id=collection_id),
        "diagnostics": [{"title": p["title"], **p["recommendation_diagnostic"]} for _, p in pairs],
        "note": "클릭 이력이 없는 사용자 기준입니다. 진단 조회는 노출 통계에 기록되지 않습니다.",
    }, headers={"Cache-Control": "no-store"})










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

# Protocol-based experiments use dedicated, authenticated routes and snapshots.
from app.services import experiment_lab, lab_delivery, lab_simulation
from app.schemas.experiment_lab import (
    DesignInput, EnrollmentInput, ActionInput, AnalysisInput, PreviewInput, DecisionInput,
)


def require_lab_action(x_experiment_admin: str = Header(default='')):
    if x_experiment_admin != '1':
        raise HTTPException(status_code=403, detail='실험실 화면에서 요청하세요.')


@router.get('/api/experiments')
async def lab_list(_: str = Depends(require_admin)):
    return await experiment_lab.list_designs()


@router.get('/api/button-experiments')
async def button_experiment_list(_: str = Depends(require_admin)):
    rows = [row for row in await experiments.list_experiments()
            if row['primary_metric'] == 'menu_button_entry_ctr']
    analyses = await asyncio.gather(
        *(experiments.get_analysis(row['id']) for row in rows), return_exceptions=True)
    items = []
    for row, analysis in zip(rows, analyses):
        item = {key: row.get(key) for key in (
            'id', 'name', 'status', 'started_at', 'ended_at', 'hypothesis',
            'analysis_plan', 'baseline_rate', 'mde', 'alpha', 'power', 'min_sample_size')}
        item['variants'] = [{key: variant[key] for key in ('variant_key', 'label', 'weight')}
                            for variant in row['variants']]
        from app.services.menu_button_experiment import VARIANTS
        for variant in item['variants']:
            variant['experience'] = VARIANTS.get(variant['variant_key'], {})
        item['analysis'] = None if isinstance(analysis, Exception) else {
            key: analysis.get(key) for key in (
                'variants', 'assigned_users', 'min_sample_size_per_variant', 'srm', 'quality')}
        items.append(item)
    from fastapi.responses import JSONResponse
    from fastapi.encoders import jsonable_encoder
    return JSONResponse(jsonable_encoder(items), headers={'Cache-Control': 'no-store'})


@router.get('/api/button-experiments/{eid}')
async def button_experiment_detail(eid: int, actor: str = Depends(require_admin)):
    response = await button_experiment_list(actor)
    import json
    for item in json.loads(response.body):
        if item['id'] == eid:
            from fastapi.responses import JSONResponse
            return JSONResponse(item, headers={'Cache-Control': 'no-store'})
    raise HTTPException(404, '버튼 실험을 찾을 수 없습니다.')


@router.post('/api/button-experiments/{eid}/{status}', dependencies=[Depends(require_lab_action)])
async def button_experiment_status(eid: int, status: str, _: str = Depends(require_admin)):
    if status not in {'running', 'paused', 'completed'}:
        raise HTTPException(400, '지원하지 않는 상태입니다.')
    rows = await experiments.list_experiments()
    row = next((r for r in rows if r['id'] == eid and r['primary_metric'] == 'menu_button_entry_ctr'), None)
    if not row:
        raise HTTPException(404, '버튼 실험을 찾을 수 없습니다.')
    if row['status'] == 'completed':
        raise HTTPException(400, '완료된 실험은 다시 변경할 수 없습니다.')
    try:
        await experiments.set_experiment_status(eid, status)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {'ok': True}


@router.post('/api/experiments', dependencies=[Depends(require_lab_action)])
async def lab_create(payload: DesignInput, actor: str = Depends(require_admin)):
    return {'id': await experiment_lab.create(payload, actor)}


@router.put('/api/experiments/{eid}', dependencies=[Depends(require_lab_action)])
async def lab_edit(eid: int, payload: DesignInput, actor: str = Depends(require_admin)):
    try:
        await experiment_lab.update_draft(eid,payload,actor)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    return {'ok':True}


@router.get('/api/experiments/{eid}/results')
async def lab_results(eid: int, _: str = Depends(require_admin)):
    try:
        return await experiment_lab.latest(eid)
    except ValueError as exc:
        raise HTTPException(404,str(exc)) from exc


@router.get('/api/experiments/{eid}/diagnostics')
async def lab_diagnostics(eid: int, _: str = Depends(require_admin)):
    data=await lab_results(eid,_)
    return {'run':data['run'],'start_blockers':data['start_blockers']}


@router.post('/api/experiments/{eid}/enrollment', dependencies=[Depends(require_lab_action)])
async def lab_enrollment(eid: int,payload: EnrollmentInput,actor: str = Depends(require_admin)):
    try:
        await experiment_lab.enrollment(eid,payload.action,payload.reason,actor)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    return {'ok':True}


@router.post('/api/experiments/{eid}/stop', dependencies=[Depends(require_lab_action)])
async def lab_stop(eid: int,payload: ActionInput,actor: str = Depends(require_admin)):
    try:
        await experiment_lab.stop(eid,payload.reason,actor)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    return {'ok':True}


@router.post('/api/experiments/{eid}/analysis-runs', dependencies=[Depends(require_lab_action)])
async def lab_analysis(eid: int,payload: AnalysisInput,actor: str = Depends(require_admin)):
    try:
        return await experiment_lab.run_analysis(eid,payload,actor)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


@router.post('/api/experiments/{eid}/simulation', dependencies=[Depends(require_lab_action)])
async def lab_simulate(eid: int,actor: str = Depends(require_admin)):
    try:
        return await lab_simulation.save(eid,actor)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


@router.post('/api/experiments/{eid}/preview', dependencies=[Depends(require_lab_action)])
async def lab_preview(eid: int,payload: PreviewInput,_: str = Depends(require_admin)):
    try:
        return await lab_delivery.preview(eid,payload.variant,payload.policy)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


@router.post('/api/experiments/{eid}/preview-override', dependencies=[Depends(require_lab_action)])
async def lab_override(eid: int,payload: PreviewInput,actor: str = Depends(require_admin)):
    try:
        return await lab_delivery.reserve(eid,payload.variant,actor,payload.policy)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


@router.delete('/api/experiments/{eid}/preview-override', dependencies=[Depends(require_lab_action)])
async def lab_cancel_override(eid: int,actor: str = Depends(require_admin)):
    from app.database import get_pool
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute('DELETE FROM lab_preview_overrides WHERE experiment_id=$1 AND user_id=$2',eid,os.getenv('DEVELOPER_ID','').strip())
            await experiment_lab.audit(conn,eid,actor,'preview_cancel','개발자 예약 취소')
    return {'ok':True}


@router.post('/api/experiments/{eid}/decision', dependencies=[Depends(require_lab_action)])
async def lab_decision(eid: int,payload: DecisionInput,actor: str = Depends(require_admin)):
    try:
        await experiment_lab.decision(eid,payload,actor)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc
    return {'ok':True}
