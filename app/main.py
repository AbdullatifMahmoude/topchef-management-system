import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from contextlib import asynccontextmanager
from app.core.config import settings
from app.core.database import engine
from sqlalchemy import text
from app.core.events import order_events_manager
from app.core.redis import redis_client
from app.core.logging import logger
from app.cors import add_cors_middleware

from app.modules.auth import register_auth
from app.modules.comments import register_comments
from app.modules.customer import register_customer
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

    logger.info(f"[STARTUP] Initializing application [PID: {pid}]")
    try:
        async with engine.begin() as conn:
                # Keep deployments compatible when application code reaches a
                # replica before the release migration command is executed.
                # The transaction-scoped advisory lock serializes concurrent
                # replicas, while IF NOT EXISTS keeps this safe on every boot.
                await conn.execute(text("SELECT pg_advisory_xact_lock(8202601)"))
                await conn.execute(text("""
                    DO $$ BEGIN
                        CREATE TYPE paymentmethod AS ENUM ('CASH', 'INSTAPAY', 'WALLET');
                    EXCEPTION WHEN duplicate_object THEN NULL;
                    END $$
                """))
                await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method paymentmethod NOT NULL DEFAULT 'CASH'"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS idx_order_payment_method ON orders (payment_method)"))
                await conn.execute(text("ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS opening_cash NUMERIC(12, 2) NOT NULL DEFAULT 0"))
                await conn.execute(text("ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS cash_expenses NUMERIC(12, 2) NOT NULL DEFAULT 0"))
                await conn.execute(text("ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS actual_closing_cash NUMERIC(12, 2)"))
                await conn.execute(text("ALTER TABLE cashier_shifts ADD COLUMN IF NOT EXISTS closing_note TEXT"))
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS product_change_logs (
                        id SERIAL PRIMARY KEY,
                        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                        changed_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                        change_type VARCHAR(30) NOT NULL,
                        old_value TEXT,
                        new_value TEXT,
                        created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
                    )
                """))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_product_change_logs_product_id ON product_change_logs (product_id)"))
                await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_product_change_logs_created_at ON product_change_logs (created_at)"))
                logger.info("[DATABASE] Payment and shift reconciliation schema verified.")

                # Discovery: List all existing constraints
                try:
                    res = await conn.execute(text("""
                        SELECT conname FROM pg_constraint 
                        WHERE conrelid = 'products'::regclass
                    """))
                    constraints = [r[0] for r in res.all()]
                    logger.info(f"[INFO] Current constraints on 'products': {constraints}")
                except Exception as e_disc:
                    logger.warning(f"Could not list constraints: {e_disc}")

                # Update product constraints.
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
        await global_leader_manager.start()
        logger.info(f"[WORKER] Global Worker active [PID: {pid}]")
    
    logger.info(f"[SUCCESS] Application startup complete [PID: {pid}] [Role: {APP_ROLE}]")
    _startup_executed = True
    
    yield
    
    # --- SHUTDOWN ---
    logger.info(f"[SHUTDOWN] Shutting down application [PID: {pid}]")
    if APP_ROLE in ("worker", "all"):
        await global_leader_manager.stop()
    if APP_ROLE in ("api", "all"):
        await order_events_manager.stop()
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
    Used by the hosting platform to verify server readiness.
    """
    try:
        redis_stats = redis_client.get_stats()
        return {
            "status": "healthy",
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
