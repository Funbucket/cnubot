from app.database import close_database, connect_database
from app.routers.cafeteria import router as cafeteria_router
from app.routers.benefits import router as benefits_router
from app.routers.admin import router as admin_router
from app.routers.help import router as help_router
from app.routers.library import router as library_router
from app.routers.promotions import router as promotions_router
from app.routers.shuttle import router as shuttle_router
from app.routers.restaurants import router as restaurants_router
from app.routers.restaurant_admin import router as restaurant_admin_router
from app.routers.insights_api import router as insights_api_router
from app.routers.admin_bridge import router as admin_bridge_router
from app.routers.admin_pages import router as admin_pages_router
from fastapi import FastAPI

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
async def startup_event():
    await connect_database()


@app.on_event("shutdown")
async def shutdown_event():
    await close_database()

app.include_router(cafeteria_router, prefix="/cafeteria", tags=["cafeteria"])
app.include_router(benefits_router, prefix="/benefits", tags=["benefits"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(shuttle_router, prefix="/shuttle", tags=["shuttle"])
app.include_router(library_router, prefix="/library", tags=["library"])
app.include_router(promotions_router, prefix="/promotions", tags=["promotions"])
app.include_router(help_router, prefix="/help", tags=["help"])
app.include_router(restaurants_router, prefix="/restaurants", tags=["restaurants"])
app.include_router(restaurant_admin_router, prefix="/admin/restaurants", tags=["admin"])

app.include_router(insights_api_router, prefix="/admin", tags=["admin"])
app.include_router(admin_bridge_router, prefix="/admin", tags=["admin"])

app.include_router(admin_pages_router, prefix="/admin", tags=["admin"])
