from fastapi import FastAPI


def register_auth(app: FastAPI):
    from app.modules.auth.router import router
    app.include_router(router)
