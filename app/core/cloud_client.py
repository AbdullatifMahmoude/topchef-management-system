import httpx
import asyncio
from typing import Optional, Any, Dict
from app.core.config import settings
from app.core.logging import logger
from app.core.sync import sync_manager

class CloudSyncClient:
    """
    Unified client for communicating with the Top Chef Cloud API.
    Handles authentication, retries, and latency tracking.
    """
    def __init__(self):
        self.base_url = settings.REMOTE_API.rstrip('/')
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=15.0
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
                # logger.debug(f"☁️ Cloud GET {endpoint} successful ({latency:.1f}ms)")
                return response.json()
            elif response.status_code == 401:
                logger.error("❌ Cloud Authentication Failed: Token might be expired.")
            else:
                logger.warning(f"⚠️ Cloud GET {endpoint} returned {response.status_code}: {response.text}")
            
            return None
        except Exception as e:
            logger.error(f"❌ Cloud Connection Error ({endpoint}): {e}")
            return None

    async def post(self, endpoint: str, json_data: Dict) -> bool:
        """Perform a POST request to the cloud."""
        try:
            response = await self._client.post(endpoint, json=json_data)
            if response.status_code in (200, 201):
                return True
            logger.warning(f"⚠️ Cloud POST {endpoint} failed ({response.status_code}): {response.text}")
            return False
        except Exception as e:
            logger.error(f"❌ Cloud POST Error ({endpoint}): {e}")
            return False

    async def close(self):
        await self._client.aclose()

# Global Singleton
cloud_client = CloudSyncClient()
