from fastapi import FastAPI
from app.modules.users.router import router

def register_user(app: FastAPI):
    app.include_router(router)