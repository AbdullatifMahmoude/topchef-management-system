from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Scope, Receive, Send

from app.core.security import decode_token
from app.core.logging import logger


# Public paths that don't require authentication
PUBLIC_PATHS = {
    "/",
    "/index.html",
    "/dashboard.html",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
    "/auth/login",
    "/pricing/preview",
    "/health",
}

# Paths that allow prefix matching (like WebSockets)
PUBLIC_PREFIXES = {
    "/docs",
    "/redoc",
    "/openapi.json",
    "/orders/ws",
}


class AuthMiddleware:
    """
    Pure ASGI Middleware for robust handling of both HTTP and WebSockets.
    BaseHTTPMiddleware is avoided here because it often interferes with 
    WebSocket handshake propagation in some ASGI environments.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        
        # ─── 0. WebSocket Bypass ───
        if scope["type"] == "websocket" or path.startswith("/orders/ws"):
            logger.info(f"⚡ Auth Bypass: allowing connection for {path}")
            await self.app(scope, receive, send)
            return

        # For HTTP requests, we wrap them in a Request object for easier handling
        request = Request(scope, receive)
        method = request.method

        # ─── 1. Public Path Bypass ───
        if path in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
            
        is_public_prefix = False
        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                is_public_prefix = True
                break
        
        if is_public_prefix:
            await self.app(scope, receive, send)
            return

        # ─── 2. Static / Media / Frontend Assets Bypass ───
        if path.startswith(("/static", "/media", "/assets", "/css", "/js", "/cashier")):
            await self.app(scope, receive, send)
            return

        # ─── 3. Domain Logic Bypasses (GET menu, POST guest orders) ───
        if method == "GET" and (
            path.startswith("/menu/categories") or 
            path.startswith("/menu/products") or
            path.startswith("/offers") or
            path.startswith("/comments")
        ):
            await self.app(scope, receive, send)
            return
        
        if method == "POST" and (
            path in ["/orders", "/orders/"] or
            path in ["/comments", "/comments/"]
        ):
             await self.app(scope, receive, send)
             return

        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        # ─── 4. Standard Auth Check ───
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            response = JSONResponse(
                status_code=401,
                content={
                    "detail": "Missing or invalid Authorization header",
                    "error_code": "AUTH_ERROR",
                },
            )
            await response(scope, receive, send)
            return

        token = auth_header.split(" ")[1]
        payload = decode_token(token)
        
        if payload is None:
            response = JSONResponse(
                status_code=401,
                content={
                    "detail": "Invalid or expired token",
                    "error_code": "AUTH_ERROR",
                },
            )
            await response(scope, receive, send)
            return

        # Inject state into request for later use in route handlers
        request.state.user_id = payload.get("user_id")
        request.state.username = payload.get("sub")
        request.state.user_role = payload.get("role")

        logger.info(
            f"👤 Authenticated: {payload.get('sub')} [{payload.get('role')}] -> {path}"
        )

        await self.app(scope, receive, send)
