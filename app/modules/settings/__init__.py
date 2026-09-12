from fastapi import FastAPI
from app.modules.settings.router import router

def register_settings(app: FastAPI):
    app.include_router(router)
    from app.modules.settings.whatsapp_webhook import router as webhook_router
    app.include_router(webhook_router)
