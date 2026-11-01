from fastapi import FastAPI


def register_menu(app: FastAPI):
    from app.modules.menu.router import router
    app.include_router(router)