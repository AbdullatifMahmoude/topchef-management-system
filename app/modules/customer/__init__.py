from fastapi import FastAPI


def register_customer(app: FastAPI):
    from app.modules.customer.router import router
    app.include_router(router)
    from app.modules.customer.account_router import router as account_router
    app.include_router(account_router)
