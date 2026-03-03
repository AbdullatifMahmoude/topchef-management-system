from fastapi import FastAPI
from app.core.config import settings
from app.modules.menu import register_menu
from app.core.database import engine, Base
from app.modules.users import register_user
from app.cors import add_cors_middleware


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION
)
add_cors_middleware(app)
register_menu(app)
register_user(app)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

@app.get("/")
def root():
    return {"message": "Welcome to RMS API"}
