from fastapi import FastAPI
from app.modules.settings.router import router

def register_settings(app: FastAPI):
    app.include_router(router)
