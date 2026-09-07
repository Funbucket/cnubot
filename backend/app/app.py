from app.database import close_database, connect_database
from app.routers.cafeteria import router as cafeteria_router
from app.routers.admin import router as admin_router
from app.routers.help import router as help_router
from app.routers.library import router as library_router
from app.routers.promotions import router as promotions_router
from app.routers.shuttle import router as shuttle_router
from app.routers.talkn import router as talkn_router
from fastapi import FastAPI

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.on_event("startup")
async def startup_event():
    await connect_database()


@app.on_event("shutdown")
async def shutdown_event():
    await close_database()

app.include_router(cafeteria_router, prefix="/cafeteria", tags=["cafeteria"])
app.include_router(admin_router, prefix="/admin", tags=["admin"])
app.include_router(shuttle_router, prefix="/shuttle", tags=["shuttle"])
app.include_router(library_router, prefix="/library", tags=["library"])
app.include_router(promotions_router, prefix="/promotions", tags=["promotions"])
app.include_router(help_router, prefix="/help", tags=["help"])
app.include_router(talkn_router, prefix="/talkn", tags=["talkn"])
