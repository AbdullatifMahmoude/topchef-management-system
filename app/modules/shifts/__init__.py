from fastapi import FastAPI

from app.modules.shifts.router import router


def register_shifts(app: FastAPI):
    app.include_router(router)
