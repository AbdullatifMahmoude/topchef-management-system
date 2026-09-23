import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.core.events import order_events_manager
from app.core.leader import global_leader_manager
from app.core.logging import logger
from app.core.observability import ObservabilityMiddleware, metrics
from app.core.redis import redis_client
from app.cors import add_cors_middleware
from app.modules.ai_menu import register_ai_menu
from app.modules.auth import register_auth
from app.modules.comments import register_comments
from app.modules.customer import register_customer
from app.modules.infrastructure.middlewares.auth import AuthMiddleware
from app.modules.infrastructure.middlewares.error_handler import (
    ErrorHandlerMiddleware,
    register_error_handlers,
)
from app.modules.menu import register_menu
from app.modules.meta_agent import register_meta_agent
from app.modules.offer import register_offer
from app.modules.orders import register_orders
from app.modules.pricing import register_pricing
from app.modules.report import register_report
from app.modules.settings import register_settings
from app.modules.shifts import register_shifts
from app.modules.users import register_user

APP_ROLE = os.getenv("APP_ROLE", "all").lower()
_startup_executed = False




@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_executed
    pid = os.getpid()
    if _startup_executed:
        yield
        return

    logger.info(f"[STARTUP] Initializing application [PID: {pid}]")
    # Database schema changes are applied exclusively through Alembic before
    # the application starts. Runtime DDL makes startup destructive and masks
    # missing deployment migrations.

    # 2. Infrastructure & Cache (Cloud Only)
    logger.info("[NETWORK] Connecting to Redis/Infrastructure...")
    if not redis_client.is_available:
        await redis_client.connect()
    logger.info("[NETWORK] Infrastructure connected.")

    # 3. Shared Services (WebSockets & Broadcasters)
    if APP_ROLE in ("api", "all"):
        logger.info("[NETWORK] Starting API Broadcaster...")
        await order_events_manager.start()
        logger.info(f"[NETWORK] API Broadcaster started [PID: {pid}]")

    # 4. Global Worker (Cloud Only)
    if APP_ROLE in ("worker", "all"):
        logger.info("[WORKER] Starting Global Workers...")
        from app.modules.infrastructure.workers.sync_worker import init_global_workers
        init_global_workers()
        if settings.WHATSAPP_OUTBOX_ENABLED:
            from app.modules.settings.whatsapp_outbox import whatsapp_outbox_worker
            global_leader_manager.on_leader_elected(whatsapp_outbox_worker.start)
            global_leader_manager.on_leader_lost(whatsapp_outbox_worker.stop)
        else:
            logger.info("[WORKER] WhatsApp outbox worker disabled")
        await global_leader_manager.start()
        logger.info(f"[WORKER] Global Worker awaiting leadership [PID: {pid}]")
    
    logger.info(f"[SUCCESS] Application startup complete [PID: {pid}] [Role: {APP_ROLE}]")
    _startup_executed = True
    
    yield
    
    # --- SHUTDOWN ---
    logger.info(f"[SHUTDOWN] Shutting down application [PID: {pid}]")
    if APP_ROLE in ("worker", "all"):
        if settings.WHATSAPP_OUTBOX_ENABLED:
            from app.modules.settings.whatsapp_outbox import whatsapp_outbox_worker
            await whatsapp_outbox_worker.stop()
        await global_leader_manager.stop()
    if APP_ROLE in ("api", "all"):
        await order_events_manager.stop()
    await redis_client.disconnect()
    from app.modules.settings.whatsapp import close_whatsapp_http_client
    await close_whatsapp_http_client()



app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)
register_error_handlers(app)

async def collect_health(db_engine=engine, cache=redis_client) -> tuple[int, dict]:
    try:
        async with db_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        logger.error("Database health check failed: %s", exc)
        return 503, {"status": "unhealthy", "database": "disconnected", "redis": cache.status_label}

    redis_status = cache.status_label
    if cache.redis is not None:
        try:
            await cache.redis.ping()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Redis health check failed: %s", exc)
            redis_status = "disconnected"
    status = "healthy" if redis_status == "connected" else "degraded"
    return 200, {"status": status, "database": "connected", "redis": redis_status}


@app.get("/health")
async def health_check():
    """
    Health check endpoint for the application.
    Used by the hosting platform to verify server readiness.
    """
    status_code, payload = await collect_health()
    return JSONResponse(status_code=status_code, content=payload)


@app.get("/metrics", include_in_schema=False)
async def application_metrics():
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

app.add_middleware(AuthMiddleware)
app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(ObservabilityMiddleware)
add_cors_middleware(app)

register_auth(app)
register_ai_menu(app)
register_menu(app)
if settings.META_AGENT_ENABLED:
    register_meta_agent(app)
else:
    logger.info("Meta Business Agent integration disabled")
register_user(app)
register_offer(app)
register_pricing(app)
register_orders(app)
register_customer(app)
register_settings(app)
register_comments(app)
register_report(app)
register_shifts(app)




frontend_path = os.path.join(os.path.dirname(__file__), "frontend")


@app.get("/")
def root():
    index_file = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Welcome to RMS API"}


# Redundant health check removed (consolidated above)


# Mount frontend last to avoid route shadowing
if os.path.exists(frontend_path):
    # Check if index.html exists to avoid mounting empty directories
    if os.path.exists(os.path.join(frontend_path, "index.html")):
        app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
    else:
        logger.warning(f"Frontend path {frontend_path} exists but index.html is missing.")
else:
    logger.warning(f"Frontend path {frontend_path} not found. UI will not be served locally.")
