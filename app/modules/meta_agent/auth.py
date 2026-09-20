import secrets

from fastapi import Depends, Request, status
from fastapi.security import APIKeyHeader

from app.core.config import settings
from app.core.exceptions import AppExceptions
from app.core.logging import logger

META_AGENT_HEADER = "X-Meta-Agent-Key"
_api_key_header = APIKeyHeader(name=META_AGENT_HEADER, auto_error=False)


async def require_meta_agent_key(
    request: Request,
    provided_key: str | None = Depends(_api_key_header),
) -> None:
    configured_key = settings.META_AGENT_API_KEY
    if not configured_key:
        logger.error("Meta Agent gateway rejected request because its API key is not configured")
        raise AppExceptions(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meta Agent integration is not configured",
            error_code="META_AGENT_NOT_CONFIGURED",
        )

    if not provided_key or not secrets.compare_digest(provided_key, configured_key):
        logger.warning("Meta Agent gateway authentication failed path=%s", request.url.path)
        raise AppExceptions(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Meta Agent credentials",
            error_code="META_AGENT_AUTH_ERROR",
        )

    logger.info("Meta Agent gateway authenticated path=%s", request.url.path)
