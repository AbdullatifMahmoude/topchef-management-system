from fastapi import FastAPI

from app.modules.ai_menu.router import router


def register_ai_menu(app: FastAPI) -> None:
    app.include_router(router)
