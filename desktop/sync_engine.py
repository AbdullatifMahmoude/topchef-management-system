import asyncio
import os
import threading
import time
from datetime import datetime
from typing import Dict, Optional

from desktop.cloud_api import cloud_api
from desktop.auth_service import auth_service
from desktop.connectivity import connectivity_monitor
from desktop.local_repository import local_repository
from desktop.logger import desktop_logger as log


class SyncEngine:
    def __init__(self) -> None:
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._wake_event = threading.Event()
        self._next_allowed_pull_at = 0.0
        self._stats: Dict[str, Optional[str]] = {
            "mode": "offline",
            "last_sync_started_at": None,
            "last_sync_finished_at": None,
            "last_pull_at": None,
            "last_push_at": None,
            "last_error": None,
            "is_online": "false",
        }
        connectivity_monitor.subscribe(self._on_connectivity_changed)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        connectivity_monitor.start()
        self._thread = threading.Thread(target=self._run_loop, name="sync-engine", daemon=True)
        self._thread.start()
        log.info("Sync engine started.")

    def stop(self) -> None:
        self._running = False
        self._wake_event.set()
        connectivity_monitor.stop()
        if self._thread:
            self._thread.join(timeout=5)

    def handle_authenticated_session(self, token: str, username: str, password: str) -> None:
        self._stats["mode"] = "online" if connectivity_monitor.is_online else "offline"
        self._wake_event.set()

    def trigger_full_sync(self, reason: str = "manual", wait: bool = False) -> None:
        log.info("Full sync requested. reason=%s", reason)
        self._wake_event.set()
        if wait:
            deadline = time.time() + 20
            while time.time() < deadline and not self._stats.get("last_sync_started_at"):
                time.sleep(0.1)

    def force_sync(self) -> None:
        self.trigger_full_sync(reason="force")

    def handle_realtime_event(self, event_type: str, data: dict) -> None:
        """Triggered by the Cloud WS Relay."""
        if event_type in ("order.created", "order.updated"):
            log.info("Real-time cloud event [%s] received. Triggering sync.", event_type)
            self._wake_event.set()

    def get_health_status(self) -> Dict[str, object]:
        return {
            **self._stats,
            "is_online": connectivity_monitor.is_online,
            "pending_sync": local_repository.get_pending_sync_count(),
            "db_size_kb": os.path.getsize(local_repository.db_path) // 1024 if os.path.exists(local_repository.db_path) else 0,
        }

    def _on_connectivity_changed(self, is_online: bool) -> None:
        self._stats["is_online"] = "true" if is_online else "false"
        self._stats["mode"] = "online" if is_online else "offline"
        if is_online:
            log.info("Reconnection detected. Sync wake-up queued.")
            self._wake_event.set()

    def _run_loop(self) -> None:
        next_background_sync = 0.0
        while self._running:
            try:
                self._wake_event.wait(timeout=5)
                self._wake_event.clear()
                online = connectivity_monitor.probe()
                now = time.time()
                if online and (now >= next_background_sync or local_repository.get_pending_sync_count() > 0):
                    self._stats["last_sync_started_at"] = datetime.utcnow().isoformat()
                    asyncio.run(self._sync_once())
                    self._stats["last_sync_finished_at"] = datetime.utcnow().isoformat()
                    next_background_sync = now + 60
            except Exception as exc:
                self._stats["last_error"] = str(exc)
                log.error("Sync loop failure: %s", exc)
                time.sleep(2)

    async def _sync_once(self) -> None:
        if not connectivity_monitor.is_online:
            self._stats["mode"] = "offline"
            return
        self._stats["mode"] = "online"
        if auth_service.has_online_session():
            await self._push_pending_transactions()
        await self._pull_cloud_state()

    async def _push_pending_transactions(self) -> None:
        queue_rows = local_repository.list_ready_queue_items(limit=100)
        if not queue_rows:
            return
        log.info("Uploading %s pending sync queue rows.", len(queue_rows))
        try:
            await cloud_api.upload_pending_queue(queue_rows)
            self._stats["last_push_at"] = datetime.utcnow().isoformat()
        except Exception as exc:
            self._stats["last_error"] = str(exc)
            log.warning("Pending upload stopped early: %s", exc)

    async def _pull_cloud_state(self) -> None:
        now = time.time()
        if now < self._next_allowed_pull_at:
            return
        log.info("Pulling latest cloud state.")
        try:
            payload = await cloud_api.fetch_master_data()
            self._stats["last_pull_at"] = datetime.utcnow().isoformat()
            self._stats["last_error"] = None
        except Exception as exc:
            self._stats["last_error"] = str(exc)
            log.error("Cloud pull failed: %s", exc)
            return
        local_repository.set_meta("last_pull_started_at", self._stats["last_pull_at"] or "")
        local_repository.upsert_master_data(payload)
        if payload.get("users"):
            local_repository.upsert_users(payload["users"])
        self._next_allowed_pull_at = time.time() + 45
        log.info("Cloud pull completed successfully.")


sync_engine = SyncEngine()
