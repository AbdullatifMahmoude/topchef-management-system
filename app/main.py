from fastapi import FastAPI
from app.core.config import settings
from app.modules.menu import register_menu
from app.core.database import engine, Base


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)

register_menu(app)

@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/")
def root():
    return {"message": "Welcome to RMS API"}
