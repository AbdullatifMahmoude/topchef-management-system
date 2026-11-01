from fastapi import FastAPI


def register_offer(app: FastAPI):
    from app.modules.offer.router import router
    app.include_router(router)
