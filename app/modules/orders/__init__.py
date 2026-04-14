from fastapi import FastAPI

def register_orders(app: FastAPI):
    from app.modules.orders.router import router
    app.include_router(router)
