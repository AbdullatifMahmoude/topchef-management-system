import asyncio
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import logger


class CloudSyncClient:
    """
    Unified client for communicating with the Top Chef Cloud API.
    Handles authentication, retries, and latency tracking.
    """

    def __init__(self):
        self.base_url = settings.REMOTE_API.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=15.0,
        )
        self._token = None
        self.last_response_bytes: int = 0

    def is_authenticated(self) -> bool:
        return bool(self._token)

    async def _handle_401(self):
        """
        Handle unauthorized responses with a silent self-renewal strategy:
        1. Decode the current JWT payload (username, user_id, role).
        2. Mint a fresh token using the local SECRET_KEY (no user interaction).
        3. Update cloud_client and the global _auth_header_cache in launcher.
        4. Only broadcast AUTH_EXPIRED if self-renewal is impossible.

        This prevents the cashier from being interrupted mid-shift when the
        cloud token expires, since the local server shares the same SECRET_KEY.
        """
        # Never mint a credential from an expired token: the account may have
        # been disabled or its permissions revoked since issuance.
        self._token = None
        self._client.headers.pop("Authorization", None)
        try:
            from app.core.events import order_events_manager
            payload = {"type": "AUTH_EXPIRED", "message": "Cloud authentication expired. Please re-login."}
            loop = asyncio.get_event_loop()
            if loop and loop.is_running():
                asyncio.create_task(order_events_manager.broadcast_all(payload))
        except Exception:  # noqa: BLE001 - expiry notification must not break auth cleanup
            logger.debug("Could not broadcast cloud authentication expiry", exc_info=True)

    def update_token(self, token: str):
        """Update the bearer token used for cloud requests."""
        if token.startswith("Bearer "):
            self._token = token
        else:
            self._token = f"Bearer {token}"
        self._client.headers.update({"Authorization": self._token})

    async def get(self, endpoint: str, params: dict | None = None) -> dict[str, Any] | None:
        """Perform a GET request to the cloud with retry logic."""
        try:
            start_time = asyncio.get_event_loop().time()
            response = await self._client.get(endpoint, params=params)
            latency = (asyncio.get_event_loop().time() - start_time) * 1000

            self.last_response_bytes = len(response.content or b"")
            if response.status_code == 200:
                logger.debug(
                    "Cloud GET %s successful (%.1fms, %s bytes)",
                    endpoint,
                    latency,
                    self.last_response_bytes,
                )
                return response.json()
            if response.status_code == 401:
                logger.warning("Cloud GET %s returned 401 — attempting silent token renewal", endpoint)
                await self._handle_401()
                if self.is_authenticated():
                    retry = await self._client.get(endpoint, params=params)
                    if retry.status_code == 200:
                        self.last_response_bytes = len(retry.content or b"")
                        return retry.json()
            else:
                logger.warning("Cloud GET %s returned status=%s", endpoint, response.status_code)

            return None
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Cloud connection error (%s): %s", endpoint, e)
            return None

    async def post(self, endpoint: str, json_data: dict) -> bool:
        """Perform a POST request to the cloud."""
        return await self.post_json(endpoint, json_data) is not None

    async def post_json(self, endpoint: str, json_data: dict) -> dict[str, Any] | None:
        """Perform a POST request to the cloud and return decoded JSON."""
        try:
            response = await self._client.post(endpoint, json=json_data)
            if response.status_code in (200, 201):
                if not response.content:
                    return {}
                return response.json()
            if response.status_code == 401:
                logger.warning("Cloud POST %s returned 401 — attempting silent token renewal", endpoint)
                await self._handle_401()
                if self.is_authenticated():
                    retry = await self._client.post(endpoint, json=json_data)
                    if retry.status_code in (200, 201):
                        return retry.json() if retry.content else {}
            else:
                logger.warning("Cloud POST %s failed status=%s", endpoint, response.status_code)
            return None
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Cloud POST error (%s): %s", endpoint, e)
            return None

    async def patch(self, endpoint: str, json_data: dict) -> dict[str, Any] | None:
        """Perform a PATCH request to the cloud."""
        try:
            response = await self._client.patch(endpoint, json=json_data)
            if response.status_code in (200, 201):
                if not response.content:
                    return {}
                return response.json()
            if response.status_code == 401:
                logger.warning("Cloud PATCH %s returned 401 — attempting silent token renewal", endpoint)
                await self._handle_401()
                if self.is_authenticated():
                    retry = await self._client.patch(endpoint, json=json_data)
                    if retry.status_code in (200, 201):
                        return retry.json() if retry.content else {}
            else:
                logger.warning("Cloud PATCH %s failed status=%s", endpoint, response.status_code)
            return None
        except (httpx.HTTPError, ValueError) as e:
            logger.error("Cloud PATCH error (%s): %s", endpoint, e)
            return None

    async def close(self):
        await self._client.aclose()


cloud_client = CloudSyncClient()
