import asyncio

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse

from app.routers.admin import require_admin
from app.schemas.restaurants import Catalog, PlaceSearch
from app.services import restaurant_catalog, restaurants

router = APIRouter(dependencies=[Depends(require_admin)])


def require_editor(x_restaurants_editor: str = Header(default="")):
    if x_restaurants_editor != "1":
        raise HTTPException(status_code=403, detail="맛집 관리 화면에서 요청해주세요.")


@router.get("/catalog")
async def get_catalog():
    try:
        catalog = await asyncio.to_thread(restaurant_catalog.read_catalog)
    except (OSError, ValueError):
        raise HTTPException(status_code=503, detail="식당 목록 파일을 읽지 못했습니다. 기존 파일을 확인해주세요.")
    return JSONResponse(catalog.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.put("/catalog", dependencies=[Depends(require_editor)])
async def put_catalog(payload: Catalog):
    try:
        saved = await asyncio.to_thread(restaurant_catalog.save_catalog, payload)
    except ValueError:
        raise HTTPException(status_code=409, detail="기존 목록이 변경되었거나 손상되었습니다. 다시 불러와 확인해주세요.")
    except OSError:
        raise HTTPException(status_code=503, detail="식당 목록을 저장하지 못했습니다.")
    return JSONResponse(saved.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


@router.post("/search", dependencies=[Depends(require_editor)])
async def search(payload: PlaceSearch):
    try:
        items = await asyncio.to_thread(restaurant_catalog.search_places, payload.query)
    except Exception:
        # Never return an HTTP exception containing an authentication header or body.
        raise HTTPException(status_code=502, detail="카카오 장소 검색에 실패했습니다. 키 설정과 사용량을 확인해주세요.")
    return JSONResponse({"items": items}, headers={"Cache-Control": "no-store"})


@router.post("/preview", dependencies=[Depends(require_editor)])
async def preview(payload: Catalog):
    now = restaurant_catalog.now_kst()
    result = []
    for message, (area, budget) in restaurants.MEAL_CHOICES.items():
        state, response, _ = restaurants.transition(None, message, payload, "", now, can_browse=False)
        result.append({"area": area, "budget": budget,
                       "eligible": len(restaurants.candidates(payload, state, now)), "response": response})
    return JSONResponse({"ratings_available": restaurant_catalog.ratings_available(payload, now),
                         "entry_enabled": restaurant_catalog.entry_enabled(), "previews": result},
                        headers={"Cache-Control": "no-store"})
