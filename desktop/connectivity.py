import threading
import time
from typing import Callable, List, Optional

import httpx

from desktop.config import config
from desktop.logger import desktop_logger as log


class ConnectivityMonitor:
    def __init__(self, base_url: str, interval_seconds: int = 5, timeout_seconds: int = 3):
        self.base_url = base_url.rstrip("/")
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self._callbacks: List[Callable[[bool], None]] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()
        self._is_online = False
        self._success_streak = 0
        self._failure_streak = 0

    @property
    def is_online(self) -> bool:
        with self._lock:
            return self._is_online

    def subscribe(self, callback: Callable[[bool], None]) -> None:
        self._callbacks.append(callback)

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="connectivity-monitor",
            daemon=True,
        )
        self._thread.start()
        log.info("Connectivity monitor started.")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)

    def probe(self) -> bool:
        url = f"{self.base_url}/health"
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(url)
            online = response.status_code in (200, 401, 403)
        except Exception:
            online = False

        previous = self.is_online
        with self._lock:
            if online:
                self._success_streak += 1
                self._failure_streak = 0
                if self._success_streak >= 1:
                    self._is_online = True
            else:
                self._failure_streak += 1
                self._success_streak = 0
                if self._failure_streak >= 3:
                    self._is_online = False

        current = self.is_online
        if previous != current:
            state = "ONLINE" if current else "OFFLINE"
            log.warning("Connectivity changed: %s", state)
            for callback in list(self._callbacks):
                try:
                    callback(current)
                except Exception as exc:
                    log.error("Connectivity callback failed: %s", exc)
        return current

    def _watch_loop(self) -> None:
        while self._running:
            try:
                self.probe()
            except Exception as exc:
                log.error("Connectivity probe failed: %s", exc)
            time.sleep(self.interval_seconds)


connectivity_monitor = ConnectivityMonitor(
    base_url=config.server_url,
    interval_seconds=max(3, int(config.get("sync_interval_seconds", 30) // 6 or 5)),
)
