from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.exceptions import AppExceptions
from app.core.logging import logger


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            response = await call_next(request)
            return response

        except AppExceptions as exc:
            # Known application errors — log at warning level
            logger.warning(
                f"Application error: {exc.error_code} - {exc.detail} "
                f"path={request.url.path} method={request.method}"
            )
            return JSONResponse(
                status_code=exc.status_code,
                content={
                    "detail": exc.detail,
                    "error_code": exc.error_code,
                },
            )

        except Exception as exc:
            # Unknown errors — log at error level with traceback
            logger.error(
                f"Unhandled exception: {type(exc).__name__}: {str(exc)} "
                f"path={request.url.path} method={request.method}",
                exc_info=True,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "error_code": "INTERNAL_ERROR",
                },
            )
