import asyncio
import os
import secrets
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo
from pathlib import Path

from app.services import experiments
from app.services import llm
from app.services import toss_sharelink
from app.services import promotion_settings
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from app.schemas.admin import VariantInput, ExperimentInput, SuggestInput, ShareTextInput

from app.services.admin_views import (
    _experiment_card,
    _recommendations_page,
    _insights_page,
    _legacy_insights_page,
    _percent,
    _insight_path_rows,
    _insight_guardrail_rows,
    _insight_fatigue_rows,
    _insight_path_funnels,
    _insight_label,
    _insight_sources,
    _insight_entry_label,
    _insight_entry_button_label,
    _insight_surfaces,
    _page,
)

router = APIRouter()
security = HTTPBasic()
_insights_cache: dict[tuple[date | None, date | None], tuple[float, dict[str, Any]]] = {}
_INSIGHTS_CACHE_SECONDS = 20


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


@router.get("/assets/admin_nav.css", response_class=PlainTextResponse, include_in_schema=False)
async def admin_navigation_css():
    path = Path(__file__).parent.parent / "static" / "admin_nav.css"
    return PlainTextResponse(path.read_text(), media_type="text/css", headers={"Cache-Control": "no-cache"})


def require_editor(x_promotion_editor: str = Header(default="")):
    if x_promotion_editor != "1":
        raise HTTPException(status_code=403, detail="관리자 상품 편집 화면에서 요청해주세요.")


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


@router.get("/insight", response_class=HTMLResponse, include_in_schema=False)
@router.get("/insights", response_class=HTMLResponse)
async def insights(
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    all_time: bool = Query(default=False),
    _: str = Depends(require_admin),
):
    if not all_time and start_date is None and end_date is None:
        end_date = datetime.now(ZoneInfo("Asia/Seoul")).date()
        start_date = end_date
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=400, detail="시작일은 종료일보다 늦을 수 없습니다.")
    cache_key = (start_date, end_date)
    cached = _insights_cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < _INSIGHTS_CACHE_SECONDS:
        data = cached[1]
    else:
        data = await experiments.get_promotion_insights(start_date, end_date)
        _insights_cache[cache_key] = (time.monotonic(), data)
    return HTMLResponse(_insights_page(data), headers={"Cache-Control": "no-store"})


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
