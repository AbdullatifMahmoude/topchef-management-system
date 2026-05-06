"""
Auto‑Updater
─────────────
Checks the FastAPI production server for newer desktop versions,
downloads the installer, and prompts the user to restart.
"""

import os
import sys
import json
import threading
import subprocess
import tempfile
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Callable

from desktop.config import config, DATA_DIR
from desktop.logger import desktop_logger as log


class Updater:
    """Non‑blocking update checker that runs in a background thread."""

    def __init__(self):
        self._server = config.server_url.rstrip("/")
        self._token = config.desktop_api_token
        self._local_version = config.get_local_version()
        self._download_dir = DATA_DIR / "updates"
        self._download_dir.mkdir(parents=True, exist_ok=True)
        self._on_update_available: Optional[Callable] = None  # UI callback
        self._checking = False

    # ── Public API ────────────────────────────────

    def set_callback(self, callback: Callable):
        """Register a callback: callback(version_info: dict)"""
        self._on_update_available = callback

    def check_now(self):
        """Trigger an immediate check (non‑blocking)."""
        if self._checking:
            return
        threading.Thread(target=self._do_check, daemon=True, name="updater").start()

    def start_periodic(self):
        """Start a background loop that checks at configured intervals."""
        interval = config.get("update_check_interval_minutes", 60) * 60
        threading.Thread(
            target=self._periodic_loop,
            args=(interval,),
            daemon=True,
            name="updater-periodic",
        ).start()

    def download_installer(self, download_url: str, filename: str = "TopChefSetup.exe") -> Optional[Path]:
        """Download the installer and return the local path."""
        target = self._download_dir / filename
        log.info("Downloading update from %s …", download_url)
        try:
            req = urllib.request.Request(download_url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=120) as resp:
                with open(target, "wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
            log.info("Update downloaded → %s", target)
            return target
        except Exception as exc:
            log.error("Update download failed: %s", exc)
            return None

    def launch_installer(self, installer_path: Path):
        """Launch the installer and close the current app."""
        log.info("Launching installer: %s", installer_path)
        try:
            subprocess.Popen(
                [str(installer_path)],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            # Give the installer a moment to start
            time.sleep(1)
            sys.exit(0)
        except Exception as exc:
            log.error("Failed to launch installer: %s", exc)

    # ── Internal ──────────────────────────────────

    def _headers(self) -> dict:
        h = {}
        if self._token:
            h["X-Desktop-Token"] = self._token
        return h

    def _do_check(self):
        self._checking = True
        try:
            url = f"{self._server}/api/desktop/version"
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            remote_ver = data.get("version", "0.0.0")
            if self._is_newer(remote_ver, self._local_version):
                log.info(
                    "Update available: %s → %s (mandatory=%s)",
                    self._local_version,
                    remote_ver,
                    data.get("mandatory", False),
                )
                if self._on_update_available:
                    self._on_update_available(data)
            else:
                log.debug("Already up to date (%s)", self._local_version)

        except urllib.error.URLError as exc:
            log.debug("Update check failed (network): %s", exc)
        except Exception as exc:
            log.error("Update check error: %s", exc)
        finally:
            self._checking = False

    def _periodic_loop(self, interval: int):
        while True:
            self._do_check()
            time.sleep(interval)

    @staticmethod
    def _is_newer(remote: str, local: str) -> bool:
        """Compare semantic versions."""
        def _parse(v: str):
            parts = v.strip().split(".")
            return tuple(int(p) for p in parts if p.isdigit())
        return _parse(remote) > _parse(local)


# Module‑level singleton
updater = Updater()
