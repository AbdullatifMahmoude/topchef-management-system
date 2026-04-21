from fastapi import FastAPI


def register_comments(app: FastAPI):
    from app.modules.comments.router import router
    app.include_router(router)
