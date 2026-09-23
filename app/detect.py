from fastapi import FastAPI

# Import routers directly
from app.modules.auth.router import router as auth_router
from app.modules.customer.router import router as customer_router
from app.modules.menu.router import router as menu_router
from app.modules.offer.router import router as offer_router
from app.modules.orders.router import router as orders_router
from app.modules.pricing.router import router as pricing_router
from app.modules.users.router import router as user_router

app = FastAPI(title="Routes Debug")

# Register routers directly so VS Code FastAPI extension can detect them
app.include_router(auth_router)
app.include_router(menu_router)
app.include_router(user_router)
app.include_router(offer_router)
app.include_router(pricing_router)
app.include_router(orders_router)
app.include_router(customer_router)