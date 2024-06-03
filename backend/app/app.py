from app.routers.cafeteria import router as cafeteria_router
from app.routers.help import router as help_router
from app.routers.library import router as library_router
from app.routers.shuttle import router as shuttle_router
from fastapi import FastAPI

app = FastAPI()

app.include_router(cafeteria_router, prefix="/cafeteria", tags=["cafeteria"])
app.include_router(shuttle_router, prefix="/shuttle", tags=["shuttle"])
app.include_router(library_router, prefix="/library", tags=["library"])
app.include_router(help_router, prefix="/help", tags=["help"])
