from fastapi import FastAPI
from app.core.database import get_sync_engine, Base
from app.core.config import settings
from app.modules.menu import register_menu

Base.metadata.create_all(bind=get_sync_engine())

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)

register_menu(app)


@app.get("/")
def root():
    return {"message": "Welcome to RMS API"}
