import asyncio
from typing import Any, Dict, Optional

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

    def update_token(self, token: str):
        """Update the bearer token used for cloud requests."""
        if token.startswith("Bearer "):
            self._token = token
        else:
            self._token = f"Bearer {token}"
        self._client.headers.update({"Authorization": self._token})

    async def get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict[str, Any]]:
        """Perform a GET request to the cloud with retry logic."""
        try:
            start_time = asyncio.get_event_loop().time()
            response = await self._client.get(endpoint, params=params)
            latency = (asyncio.get_event_loop().time() - start_time) * 1000

            if response.status_code == 200:
                logger.debug("Cloud GET %s successful (%.1fms)", endpoint, latency)
                return response.json()
            if response.status_code == 401:
                logger.error("Cloud authentication failed: token might be expired")
            else:
                logger.warning("Cloud GET %s returned %s: %s", endpoint, response.status_code, response.text)

            return None
        except Exception as e:
            logger.error("Cloud connection error (%s): %s", endpoint, e)
            return None

    async def post(self, endpoint: str, json_data: Dict) -> bool:
        """Perform a POST request to the cloud."""
        return await self.post_json(endpoint, json_data) is not None

    async def post_json(self, endpoint: str, json_data: Dict) -> Optional[Dict[str, Any]]:
        """Perform a POST request to the cloud and return decoded JSON."""
        try:
            response = await self._client.post(endpoint, json=json_data)
            if response.status_code in (200, 201):
                if not response.content:
                    return {}
                return response.json()
            logger.warning("Cloud POST %s failed (%s): %s", endpoint, response.status_code, response.text)
            return None
        except Exception as e:
            logger.error("Cloud POST error (%s): %s", endpoint, e)
            return None

    async def patch(self, endpoint: str, json_data: Dict) -> Optional[Dict[str, Any]]:
        """Perform a PATCH request to the cloud."""
        try:
            response = await self._client.patch(endpoint, json=json_data)
            if response.status_code in (200, 201):
                if not response.content:
                    return {}
                return response.json()
            logger.warning("Cloud PATCH %s failed (%s): %s", endpoint, response.status_code, response.text)
            return None
        except Exception as e:
            logger.error("Cloud PATCH error (%s): %s", endpoint, e)
            return None

    async def close(self):
        await self._client.aclose()


cloud_client = CloudSyncClient()
