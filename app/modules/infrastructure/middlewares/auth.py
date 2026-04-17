from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.security import decode_token
from app.core.logging import logger


# Public paths that don't require authentication
PUBLIC_PATHS = {
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/auth/login",
    "/pricing/preview",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        method = request.method

        # ─── 1. Public Path Bypass ───
        if path in PUBLIC_PATHS or path.startswith(("/docs", "/redoc", "/openapi.json")):
            return await call_next(request)

        # ─── 2. Static / Media Bypass (Optional but good if you have images) ───
        if path.startswith("/static") or path.startswith("/media"):
            return await call_next(request)

        # ─── 3. Web Menu / Public API Bypass ───
        # Allow viewing categories, products, and offers
        if method == "GET" and (
            path.startswith("/menu/categories") or 
            path.startswith("/menu/products") or
            path.startswith("/offers")
        ):
            return await call_next(request)
        
        # Allow creating orders (anonymous/guest orders)
        if method == "POST" and path in ["/orders", "/orders/"]:
             return await call_next(request)

        # ─── 4. Standard Auth Check ───
        if method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Missing or invalid Authorization header",
                    "error_code": "AUTH_ERROR",
                },
            )

        token = auth_header.split(" ")[1]

        payload = decode_token(token)
        if payload is None:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Invalid or expired token",
                    "error_code": "AUTH_ERROR",
                },
            )

        request.state.user_id = payload.get("user_id")
        request.state.username = payload.get("sub")
        request.state.user_role = payload.get("role")

        logger.info(
            f"Authenticated request: user={payload.get('sub')} "
            f"role={payload.get('role')} path={path}"
        )

        return await call_next(request)
