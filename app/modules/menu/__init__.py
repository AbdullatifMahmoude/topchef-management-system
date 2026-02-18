from fastapi import FastAPI
from app.modules.menu.router import router

def register_menu(app: FastAPI):
    app.include_router(router)