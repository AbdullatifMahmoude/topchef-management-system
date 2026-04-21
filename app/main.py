from fastapi import FastAPI

from app.core.config import settings
from app.core.database import engine, Base
from app.core.redis import redis_client
from app.cors import add_cors_middleware

# Module registrations
from app.modules.menu import register_menu
from app.modules.users import register_user
from app.modules.auth import register_auth
from app.modules.offer import register_offer
from app.modules.pricing import register_pricing
from app.modules.orders import register_orders
from app.modules.customer import register_customer
from app.modules.settings import register_settings
from app.modules.comments import register_comments
from app.modules.settings.models import AppSetting # For metadata registration
# Infrastructure middlewares
from app.modules.infrastructure.middlewares.auth import AuthMiddleware
from app.modules.infrastructure.middlewares.error_handler import ErrorHandlerMiddleware


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
)

# ─── Middleware Stack (order matters: first added = outermost) ───
# 1. Error handler wraps everything — catches unhandled exceptions
app.add_middleware(ErrorHandlerMiddleware)

# 2. Auth middleware verifies JWT on protected routes
app.add_middleware(AuthMiddleware)

# 3. CORS middleware
add_cors_middleware(app)

# ─── Register Modules ───
register_auth(app)    # /auth/login (public)
register_menu(app)    # /menu/* (protected)
register_user(app)    # /user/* (protected)
register_offer(app)   # /offers/* (protected)
register_pricing(app) # /pricing/* (public/protected)
register_orders(app)  # /orders/* (protected)
register_customer(app) # /customers/* (protected)
register_settings(app) # /settings/* (admin/cashier)
register_comments(app) # /comments/* (public - no auth required)


@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Initialize Redis connection
    await redis_client.connect()


@app.on_event("shutdown")
async def shutdown():
    # Close Redis connection gracefully
    await redis_client.disconnect()


@app.get("/")
def root():
    return {"message": "Welcome to RMS API"}


@app.get("/health")
async def health_check():
    """System health check with Redis performance stats."""
    redis_status = "connected" if redis_client.redis else "disconnected"
    redis_stats = redis_client.get_stats()
    
    return {
        "status": "healthy",
        "redis": {
            "status": redis_status,
            "stats": redis_stats
        },
        "database": "connected"
    }
