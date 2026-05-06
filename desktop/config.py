"""
Desktop Configuration Manager
──────────────────────────────
Loads settings.json and exposes typed accessors.
Falls back to sensible defaults when keys are missing.
"""

import json
import sys
import uuid
from pathlib import Path
from typing import Any


def _get_base_dir() -> Path:
    """Return the directory where the desktop package lives.
    Works both in development and when frozen with PyInstaller.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR = _get_base_dir()
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
ASSETS_DIR = BASE_DIR / "assets"
DB_PATH = DATA_DIR / "topchef_local.db"
SETTINGS_PATH = BASE_DIR / "settings.json"
VERSION_PATH = BASE_DIR / "version.txt"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
ASSETS_DIR.mkdir(parents=True, exist_ok=True)

_DEFAULTS = {
    "server_url": "https://topchef-system.fastapicloud.dev",
    "local_port": 8199,
    "auto_start_with_windows": False,
    "minimize_to_tray": True,
    "check_updates_on_start": True,
    "update_check_interval_minutes": 60,
    "sync_interval_seconds": 30,
    "printer_name": "XPrinter",
    "printer_width_mm": 80,
    "printer_use_escpos": True,
    "printer_auto_cut": True,
    "language": "ar",
    "theme": "dark",
    "log_level": "INFO",
    "log_max_bytes": 5_242_880,
    "log_backup_count": 5,
    "desktop_api_token": "",
    "device_id": "",
}


class DesktopConfig:
    """Singleton‑ish config class backed by settings.json."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._loaded = False
        return cls._instance

    def __init__(self):
        if not self._loaded:
            self._data: dict = {}
            self.load()
            self._loaded = True

    # ── I/O ────────────────────────────────────────

    def load(self):
        if SETTINGS_PATH.exists():
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {}
        # Ensure device_id is always populated
        if not self.get("device_id"):
            self.set("device_id", uuid.uuid4().hex[:12])
            self.save()

    def save(self):
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=4, ensure_ascii=False)

    # ── Accessors ──────────────────────────────────

    def get(self, key: str, fallback: Any = None) -> Any:
        return self._data.get(key, _DEFAULTS.get(key, fallback))

    def set(self, key: str, value: Any):
        self._data[key] = value

    def all(self) -> dict:
        merged = {**_DEFAULTS, **self._data}
        return merged

    # ── Shortcuts ──────────────────────────────────

    @property
    def server_url(self) -> str:
        return self.get("server_url")

    @property
    def local_port(self) -> int:
        return int(self.get("local_port"))

    @property
    def printer_name(self) -> str:
        return self.get("printer_name")

    @property
    def printer_width_mm(self) -> int:
        return int(self.get("printer_width_mm"))

    @property
    def device_id(self) -> str:
        return self.get("device_id")

    @property
    def desktop_api_token(self) -> str:
        return self.get("desktop_api_token")

    def get_local_version(self) -> str:
        if VERSION_PATH.exists():
            return VERSION_PATH.read_text(encoding="utf-8").strip()
        return "0.0.0"


# Module‑level convenience instance
config = DesktopConfig()
