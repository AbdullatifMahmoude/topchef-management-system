import json
import os
import sys
from pathlib import Path
from threading import RLock


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(os.environ.get("LOCALAPPDATA", Path(sys.executable).parent)) / "TopChefPrintAgent"
    return Path(__file__).resolve().parent


BASE_DIR = _base_dir()
BASE_DIR.mkdir(parents=True, exist_ok=True)
SETTINGS_PATH = BASE_DIR / "settings.json"
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULTS = {
    "local_port": 8199,
    "printer_names": [],
    "printer_width_mm": 80,
}


class PrintAgentConfig:
    def __init__(self):
        self._lock = RLock()
        self._data = {}
        self.load()

    def load(self):
        with self._lock:
            try:
                value = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                self._data = value if isinstance(value, dict) else {}
            except (OSError, json.JSONDecodeError):
                self._data = {}

    def save(self) -> bool:
        with self._lock:
            temp_path = SETTINGS_PATH.with_suffix(".json.tmp")
            try:
                temp_path.write_text(
                    json.dumps(self.all(), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                os.replace(temp_path, SETTINGS_PATH)
                return True
            except OSError:
                temp_path.unlink(missing_ok=True)
                return False

    def get(self, key, fallback=None):
        return self._data.get(key, DEFAULTS.get(key, fallback))

    def set(self, key, value):
        with self._lock:
            self._data[key] = value

    def all(self):
        return {**DEFAULTS, **self._data}

    @property
    def local_port(self) -> int:
        return int(self.get("local_port"))

    @property
    def printer_names(self) -> list[str]:
        names = self.get("printer_names", [])
        return [str(name) for name in names] if isinstance(names, list) else []

    @property
    def printer_name(self) -> str:
        return self.printer_names[0] if self.printer_names else ""

    @property
    def printer_width_mm(self) -> int:
        return int(self.get("printer_width_mm"))


config = PrintAgentConfig()
