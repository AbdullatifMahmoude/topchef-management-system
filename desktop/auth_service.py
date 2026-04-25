import base64
import json
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from desktop.config import DATA_DIR, config
from desktop.local_repository import local_repository
from desktop.logger import desktop_logger as log


class SecureSessionStore:
    def __init__(self) -> None:
        self.path = Path(DATA_DIR) / "session.dat"

    def save(self, payload: Dict[str, Any]) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        protected = self._protect(raw)
        self.path.write_bytes(protected)

    def load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self._unprotect(self.path.read_bytes()).decode("utf-8"))
        except Exception as exc:
            log.warning("Failed to read cached session: %s", exc)
            return {}

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()

    @staticmethod
    def _protect(data: bytes) -> bytes:
        try:
            import win32crypt  # type: ignore

            return win32crypt.CryptProtectData(data, "TopChefDesktop", None, None, None, 0)
        except Exception:
            return base64.b64encode(data)

    @staticmethod
    def _unprotect(data: bytes) -> bytes:
        try:
            import win32crypt  # type: ignore

            return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]
        except Exception:
            return base64.b64decode(data)


class AuthService:
    def __init__(self) -> None:
        self.session_store = SecureSessionStore()
        self._access_token: Optional[str] = None
        self._online_session_active = False

    def get_access_token(self) -> Optional[str]:
        return self._access_token

    def has_online_session(self) -> bool:
        token = self.get_access_token()
        return bool(self._online_session_active and token and token != "offline-session")

    async def login(self, username: str, password: str) -> Dict[str, Any]:
        online_error: Optional[Exception] = None
        try:
            online = await self._login_online(username, password)
            local_repository.cache_authenticated_user(online, password)
            self._save_session(
                username=username,
                password=password,
                access_token=online["access_token"],
                user_id=online["user_id"],
                role=str(online["role"]),
                full_name=online.get("full_name") or username,
                activate_online_session=True,
            )
            from desktop.sync_engine import sync_engine

            sync_engine.handle_authenticated_session(
                token=online["access_token"],
                username=username,
                password=password,
            )
            sync_engine.trigger_full_sync(reason="post-login", wait=False)
            local_repository.log_event("LOGIN_SUCCESS", online["user_id"], {"mode": "online", "username": username})
            return online
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                local_repository.log_event("LOGIN_FAILED", None, {"mode": "online", "username": username})
                raise
            online_error = exc
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            online_error = exc
        except Exception as exc:
            online_error = exc

        offline_user = local_repository.authenticate_offline(username, password)
        if offline_user:
            payload = {
                "access_token": "offline-session",
                "token_type": "bearer",
                "user_id": offline_user["cloud_id"] or offline_user["id"],
                "username": offline_user["username"],
                "full_name": offline_user.get("full_name") or offline_user["username"],
                "role": offline_user["role"],
                "mode": "offline",
            }
            self._save_session(
                username=username,
                password=password,
                access_token="offline-session",
                user_id=payload["user_id"],
                role=payload["role"],
                full_name=payload["full_name"],
                activate_online_session=False,
            )
            local_repository.log_event("LOGIN_SUCCESS", payload["user_id"], {"mode": "offline", "username": username})
            return payload

        if online_error:
            raise online_error
        raise PermissionError("Offline login unavailable for this user")

    async def refresh_access_token(self) -> Optional[str]:
        session = self.session_store.load()
        username = session.get("username")
        password = session.get("password")
        if not username or not password:
            log.warning("Token refresh skipped: no cached credentials.")
            return None
        try:
            response = await self._login_online(username, password)
            local_repository.cache_authenticated_user(response, password)
            self._save_session(
                username=username,
                password=password,
                access_token=response["access_token"],
                user_id=response["user_id"],
                role=str(response["role"]),
                full_name=response.get("full_name") or username,
                activate_online_session=True,
            )
            log.info("Access token refreshed successfully.")
            return response["access_token"]
        except Exception as exc:
            log.error("Token refresh failed: %s", exc)
            return None

    async def _login_online(self, username: str, password: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{config.server_url.rstrip('/')}/auth/login",
                json={"username": username, "password": password},
            )
            response.raise_for_status()
            payload = response.json()
            payload["role"] = str(payload.get("role"))
            payload["full_name"] = payload.get("full_name") or username
            self._access_token = payload["access_token"]
            return payload

    def _save_session(
        self,
        username: str,
        password: str,
        access_token: str,
        user_id: int,
        role: str,
        full_name: str,
        activate_online_session: bool,
    ) -> None:
        self._access_token = access_token
        self._online_session_active = activate_online_session and access_token != "offline-session"
        self.session_store.save(
            {
                "username": username,
                "password": password,
                "access_token": access_token,
                "user_id": user_id,
                "role": role,
                "full_name": full_name,
            }
        )

    def logout_runtime_session(self) -> None:
        self._access_token = None
        self._online_session_active = False


auth_service = AuthService()
