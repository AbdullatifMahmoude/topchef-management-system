from fastapi import FastAPI


def register_pricing(app: FastAPI):
    from app.modules.pricing.router import router
    app.include_router(router)
