from fastapi import FastAPI

from app.modules.meta_agent.router import router


def register_meta_agent(app: FastAPI) -> None:
    app.include_router(router)
