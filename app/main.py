import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import Base, engine
from app.core.redis import redis_client
from app.cors import add_cors_middleware

from app.modules.auth import register_auth
from app.modules.comments import register_comments
from app.modules.customer import register_customer
from app.modules.desktop_updates import register_desktop_updates
from app.modules.infrastructure.middlewares.auth import AuthMiddleware
from app.modules.infrastructure.middlewares.error_handler import ErrorHandlerMiddleware
from app.modules.menu import register_menu
from app.modules.offer import register_offer
from app.modules.orders import register_orders
from app.modules.pricing import register_pricing
from app.modules.settings import register_settings
from app.modules.users import register_user

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
)

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(AuthMiddleware)
add_cors_middleware(app)

register_auth(app)
register_menu(app)
register_user(app)
register_offer(app)
register_pricing(app)
register_orders(app)
register_customer(app)
register_settings(app)
register_comments(app)
register_desktop_updates(app)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await redis_client.connect()


@app.on_event("shutdown")
async def shutdown():
    await redis_client.disconnect()


frontend_path = os.path.join(os.path.dirname(__file__), "frontend")


@app.get("/")
def root():
    index_file = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Welcome to RMS API"}


@app.get("/health")
async def health_check():
    redis_stats = redis_client.get_stats()

    return {
        "status": "healthy",
        "redis": {
            "status": redis_client.status_label,
            "stats": redis_stats,
        },
        "database": "connected",
    }


if os.path.exists(frontend_path):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
