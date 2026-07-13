from app.database import close_database, connect_database
from app.routers.cafeteria import router as cafeteria_router
from app.routers.help import router as help_router
from app.routers.library import router as library_router
from app.routers.shuttle import router as shuttle_router
from fastapi import FastAPI

app = FastAPI()


@app.on_event("startup")
async def startup_event():
    await connect_database()


@app.on_event("shutdown")
async def shutdown_event():
    await close_database()

app.include_router(cafeteria_router, prefix="/cafeteria", tags=["cafeteria"])
app.include_router(shuttle_router, prefix="/shuttle", tags=["shuttle"])
app.include_router(library_router, prefix="/library", tags=["library"])
app.include_router(help_router, prefix="/help", tags=["help"])
