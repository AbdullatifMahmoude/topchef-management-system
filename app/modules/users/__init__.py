from fastapi import FastAPI

def register_user(app: FastAPI):
    from app.modules.users.router import router
    app.include_router(router)