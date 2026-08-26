from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.exceptions import AppExceptions
from app.core.logging import logger


def _error_response(request: Request, status_code: int, detail, error_code: str) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    content = {"detail": detail, "error_code": error_code}
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=content)


async def app_exception_handler(request: Request, exc: AppExceptions) -> JSONResponse:
    logger.warning("Application error code=%s path=%s method=%s", exc.error_code, request.url.path, request.method)
    return _error_response(request, exc.status_code, exc.detail, exc.error_code or "APPLICATION_ERROR")


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    error_code = {401: "AUTH_ERROR", 403: "FORBIDDEN", 404: "NOT_FOUND"}.get(exc.status_code, "HTTP_ERROR")
    return _error_response(request, exc.status_code, exc.detail, error_code)


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{
        "field": ".".join(str(part) for part in item["loc"] if part not in ("body", "query", "path")),
        "message": item["msg"],
        "type": item["type"],
    } for item in exc.errors()]
    return _error_response(request, 422, errors, "VALIDATION_ERROR")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppExceptions, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Last-resort boundary for unexpected failures; known errors use handlers above."""

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception:  # noqa: BLE001 - this is the process-level error boundary
            logger.exception("Unhandled exception path=%s method=%s", request.url.path, request.method)
            return _error_response(request, 500, "Internal server error", "INTERNAL_ERROR")
