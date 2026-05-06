"""
Business logic for desktop update distribution.

The current version metadata is stored in a JSON file so that ops can update
it without redeploying the API.  For a more advanced setup, move this to a DB
table or admin panel.
"""

import json
import os
from pathlib import Path
from typing import Optional

from .schemas import VersionInfo, ChangelogEntry, ChangelogResponse

# ── Where we keep the authoritative version metadata ──
_BASE = Path(__file__).resolve().parent
_VERSION_FILE = _BASE / "version_meta.json"
_CHANGELOG_FILE = _BASE / "changelog.json"
_DOWNLOADS_DIR = _BASE / "downloads"          # Local mirror (optional)


def _read_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


# ─── Public helpers ───────────────────────────────────────────

def get_latest_version() -> VersionInfo:
    """Return the latest version info from the JSON file."""
    raw = _read_json(_VERSION_FILE)
    if not raw:
        # Sensible defaults when the file hasn't been created yet
        return VersionInfo(
            version="1.0.0",
            mandatory=False,
            notes="Initial release",
            download_url="",
        )
    return VersionInfo(**raw)


def set_latest_version(info: VersionInfo) -> None:
    """Persist a new version record (called by admin tooling)."""
    _write_json(_VERSION_FILE, info.model_dump())


def get_changelog() -> ChangelogResponse:
    raw = _read_json(_CHANGELOG_FILE)
    if isinstance(raw, list):
        entries = [ChangelogEntry(**e) for e in raw]
    else:
        entries = []
    return ChangelogResponse(entries=entries)


def get_download_path(filename: str) -> Optional[Path]:
    """Return the absolute path to an installer file if it exists locally."""
    target = _DOWNLOADS_DIR / filename
    if target.exists() and target.is_file():
        return target
    return None


def installer_exists(filename: str) -> bool:
    return (_DOWNLOADS_DIR / filename).is_file()
