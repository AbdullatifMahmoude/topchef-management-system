from fastapi import FastAPI
from .router import router

def register_report(app: FastAPI):
    app.include_router(router)
