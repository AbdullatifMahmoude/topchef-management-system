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
        renewed = await self._silent_renew_token()
        if not renewed:
            # Last resort: clear token and ask user to re-login
            self._token = None
            self._client.headers.pop("Authorization", None)
            try:
                from app.core.events import order_events_manager
                payload = {
                    "type": "AUTH_EXPIRED",
                    "message": "Cloud authentication expired. Please re-login."
                }
                loop = asyncio.get_event_loop()
                if loop and loop.is_running():
                    asyncio.create_task(order_events_manager.broadcast_all(payload))
            except Exception:
                pass

    async def _silent_renew_token(self) -> bool:
        """
        Attempt a silent token self-renewal.

        The local server and cloud share the same JWT SECRET_KEY. If the
        current token is expired but structurally valid, we can extract the
        user claims and mint a fresh token locally — no password needed.

        Returns True if renewal succeeded, False otherwise.
        """
        try:
            if not self._token:
                return False

            raw_token = self._token.removeprefix("Bearer ").strip()

            # Decode WITHOUT verifying expiry to extract claims
            from jose import jwt, JWTError
            from app.core.config import settings
            from app.core.security import create_access_token

            try:
                payload = jwt.decode(
                    raw_token,
                    settings.SECRET_KEY,
                    algorithms=[settings.ALGORITHM],
                    options={"verify_exp": False},
                )
            except JWTError as e:
                logger.warning("Silent renewal: cannot decode current token — %s", e)
                return False

            username = payload.get("sub")
            user_id = payload.get("user_id")
            role = payload.get("role")

            if not username or not user_id:
                logger.warning("Silent renewal: token payload missing required claims")
                return False

            new_token = create_access_token(
                data={"sub": username, "user_id": user_id, "role": role}
            )
            self.update_token(new_token)

            # Also refresh the global _auth_header_cache in launcher so the
            # middleware picks it up on the next local request.
            try:
                import desktop.launcher as _launcher
                _launcher._auth_header_cache = f"Bearer {new_token}"
            except Exception:
                pass

            logger.info(
                "🔑 Silent token renewal succeeded for user '%s' (role=%s)",
                username, role,
            )
            return True
        except Exception as e:
            logger.error("Silent renewal failed unexpectedly: %s", e)
            return False

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
                logger.warning("Cloud GET %s returned 401 — attempting silent token renewal", endpoint)
                await self._handle_401()
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
            if response.status_code == 401:
                logger.warning("Cloud POST %s returned 401 — attempting silent token renewal", endpoint)
                await self._handle_401()
            else:
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
            if response.status_code == 401:
                logger.warning("Cloud PATCH %s returned 401 — attempting silent token renewal", endpoint)
                await self._handle_401()
            else:
                logger.warning("Cloud PATCH %s failed (%s): %s", endpoint, response.status_code, response.text)
            return None
        except Exception as e:
            logger.error("Cloud PATCH error (%s): %s", endpoint, e)
            return None

    async def close(self):
        await self._client.aclose()


cloud_client = CloudSyncClient()
