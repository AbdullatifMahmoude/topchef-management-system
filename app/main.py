import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import Base, engine
from sqlalchemy import text
from app.core.events import order_events_manager
from app.core.redis import redis_client
from app.core.logging import logger
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
from app.modules.report import register_report
from app.modules.shifts import register_shifts
from app.core.leader import global_leader_manager

APP_ROLE = os.getenv("APP_ROLE", "all").lower()
_startup_executed = False




@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_executed
    pid = os.getpid()
    if _startup_executed:
        yield
        return

    logger.info(f"[STARTUP] Initializing application [PID: {pid}] [Mode: {settings.RUNTIME_MODE}]")
    
    if settings.RUNTIME_MODE == "desktop":
        logger.info("[DESKTOP] Desktop Mode: Verifying local DB schema...")
        async with engine.begin() as conn:
            # 1. Create any missing tables
            await conn.run_sync(Base.metadata.create_all)
            
            # 2. Self-heal missing columns (SQLite doesn't support 'IF NOT EXISTS' in ALTER TABLE easily)
            tables_to_fix = [
                "categories", "products", "variants", "users", "customers", 
                "customer_addresses", "offers", "comments", "orders", 
                "order_items", "order_status_history", "app_settings"
            ]
            
            for table in tables_to_fix:
                try:
                    # Check existing columns
                    res = await conn.execute(text(f"PRAGMA table_info({table})"))
                    existing_cols = [r[1] for r in res.all()]
                    
                    if "is_deleted" not in existing_cols:
                        logger.info(f"Adding 'is_deleted' to {table}...")
                        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN is_deleted BOOLEAN DEFAULT 0 NOT NULL"))
                    
                    if "updated_at" not in existing_cols:
                        # Only certain tables need updated_at for sync
                        if table in ["categories", "products", "variants", "customers", "customer_addresses", "offers", "comments", "app_settings", "order_items", "order_status_history"]:
                            logger.info(f"Adding 'updated_at' to {table}...")
                            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN updated_at DATETIME DEFAULT CURRENT_TIMESTAMP"))
                except Exception as e:
                    logger.warning(f"Could not self-heal table {table}: {e}")
                    
        logger.info("[DESKTOP] Desktop Mode: Local DB schema verified.")


    # Cloud/General Self-Healing (Postgres Only)
    if settings.RUNTIME_MODE != "desktop":
        try:
            async with engine.begin() as conn:
                # A. Ensure active_devices exists
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS active_devices (
                        device_id VARCHAR(100) PRIMARY KEY,
                        last_seen TIMESTAMP WITHOUT TIME ZONE,
                        version VARCHAR(20),
                        ip_address VARCHAR(50)
                    )
                """))
                
                # B. Discovery: List all existing constraints
                try:
                    res = await conn.execute(text("""
                        SELECT conname FROM pg_constraint 
                        WHERE conrelid = 'products'::regclass
                    """))
                    constraints = [r[0] for r in res.all()]
                    logger.info(f"[INFO] Current constraints on 'products': {constraints}")
                except Exception as e_disc:
                    logger.warning(f"Could not list constraints: {e_disc}")

                # C. Nuclear Drop of strict constraints
                try:
                    # 1. Drop the name-only unique constraint
                    await conn.execute(text("ALTER TABLE products DROP CONSTRAINT IF EXISTS products_product_name_key CASCADE"))
                    await conn.execute(text("DROP INDEX IF EXISTS products_product_name_key CASCADE"))
                    
                    # 2. Reset the composite one
                    await conn.execute(text("ALTER TABLE products DROP CONSTRAINT IF EXISTS uq_product_name_cat_id CASCADE"))
                    await conn.execute(text("ALTER TABLE products ADD CONSTRAINT uq_product_name_cat_id UNIQUE (product_name, cat_id)"))
                    
                    logger.info("[SECURITY] Cloud DB hardening successful: Product constraints updated.")
                except Exception as inner_e:
                    logger.error(f"[ERROR] Failed to apply product constraint fix: {inner_e}")
                    
        except Exception as e:
            logger.warning(f"Self-healing database update skipped or failed: {e}")

    # 2. Infrastructure & Cache (Cloud Only)
    if settings.RUNTIME_MODE != "desktop":
        logger.info("[NETWORK] Connecting to Redis/Infrastructure...")
        if not redis_client.is_available:
            await redis_client.connect()
        logger.info("[NETWORK] Infrastructure connected.")
    else:
        logger.info("[DESKTOP] Desktop Mode: Skipping external Redis connection.")
        # Ensure the client is initialized with InMemoryCache for desktop
        await redis_client.connect()

    # 3. Shared Services (WebSockets & Broadcasters)
    if APP_ROLE in ("api", "all"):
        logger.info("[NETWORK] Starting API Broadcaster...")
        await order_events_manager.start()
        logger.info(f"[NETWORK] API Broadcaster started [PID: {pid}]")

    # 4. Global Worker (Cloud Only)
    if settings.RUNTIME_MODE != "desktop" and APP_ROLE in ("worker", "all"):
        logger.info("[WORKER] Starting Global Workers...")
        from app.modules.infrastructure.workers.sync_worker import init_global_workers
        init_global_workers()
        await global_leader_manager.start()
        logger.info(f"[WORKER] Global Worker active [PID: {pid}]")
    elif settings.RUNTIME_MODE == "desktop":
        logger.info("[DESKTOP] Desktop Mode: Global Workers/Leader Election disabled.")
    
    logger.info(f"[SUCCESS] Application startup complete [PID: {pid}] [Role: {APP_ROLE}]")
    _startup_executed = True
    
    yield
    
    # --- SHUTDOWN ---
    logger.info(f"[SHUTDOWN] Shutting down application [PID: {pid}]")
    if settings.RUNTIME_MODE != "desktop" and APP_ROLE in ("worker", "all"):
        await global_leader_manager.stop()
    if APP_ROLE in ("api", "all"):
        await order_events_manager.stop()
    if settings.RUNTIME_MODE != "desktop":
        await redis_client.disconnect()



app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
)

@app.get("/health")
async def health_check():
    """
    Health check endpoint for the application.
    Used by the desktop launcher to verify server readiness.
    """
    try:
        redis_stats = redis_client.get_stats()
        return {
            "status": "healthy",
            "mode": settings.RUNTIME_MODE,
            "redis": {
                "status": redis_client.status_label,
                "stats": redis_stats,
            },
            "database": "connected",
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "detail": str(e)}
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
