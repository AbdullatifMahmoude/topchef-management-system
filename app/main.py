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
from app.core.leader import global_leader_manager

APP_ROLE = os.getenv("APP_ROLE", "all").lower()
_startup_executed = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _startup_executed
    
    # --- STARTUP ---
    pid = os.getpid()
    
    if _startup_executed:
        logger.warning(f"⚠️ Startup already executed for PID {pid}. Skipping duplicate call.")
        yield
        return

    logger.info(f"🚀 Initializing application [PID: {pid}] [Mode: {settings.RUNTIME_MODE}]")
    logger.info("🚀 APP STARTUP INITIATED - Running self-healing logic...")
    
    # 1. Database & Role Initialization
    if settings.RUNTIME_MODE == "desktop":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("🖥️ Desktop Mode: Local DB tables verified.")

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
                    logger.info(f"🔎 Current constraints on 'products': {constraints}")
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
                    
                    logger.info("🛡️ Cloud DB hardening successful: Product constraints updated.")
                except Exception as inner_e:
                    logger.error(f"❌ Failed to apply product constraint fix: {inner_e}")
                    
        except Exception as e:
            logger.warning(f"Self-healing database update skipped or failed: {e}")
    
    # 2. Shared Services (WebSockets & Broadcasters)
    # Every API instance needs its own listener to notify its connected clients.
    if APP_ROLE in ("api", "all"):
        await order_events_manager.start()
        logger.info(f"📡 API Broadcaster started [PID: {pid}]")

    # 3. Global Worker (Leader Election for Singletons)
    # Only one instance handles these globally.
    if APP_ROLE in ("worker", "all"):
        if not redis_client.is_available:
            await redis_client.connect()
            
        # Initialize Global Task Registry
        from app.modules.infrastructure.workers.sync_worker import init_global_workers
        init_global_workers()
        
        await global_leader_manager.start()
        logger.info(f"👷 Global Worker active [PID: {pid}]")
    
    logger.info(f"✅ Application startup complete [PID: {pid}] [Role: {APP_ROLE}]")
    _startup_executed = True
    
    yield
    
    # --- SHUTDOWN ---
    logger.info(f"🛑 Shutting down application [PID: {pid}]")
    if APP_ROLE in ("worker", "all"):
        await global_leader_manager.stop()
    if APP_ROLE in ("api", "all"):
        await order_events_manager.stop()
    await redis_client.disconnect()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan
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
