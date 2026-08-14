"""Desktop sync health tracker — consecutive failures, heartbeat, egress metrics."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


CONSECUTIVE_FAILURE_WARNING_THRESHOLD = 5
QUARANTINE_AFTER_FAILURES = 3


@dataclass
class SyncHealthState:
    healthy: bool = True
    consecutive_failures: int = 0
    last_success_at: float | None = None
    last_failure_at: float | None = None
    last_error: str | None = None
    last_master_pull_at: float | None = None
    last_master_pull_bytes: int = 0
    last_master_pull_forced: bool = False
    total_master_pull_bytes: int = 0
    quarantined_rows: int = 0
    warnings: list[str] = field(default_factory=list)


class SyncHealthTracker:
    """Thread-safe-enough singleton for sync loop observability."""

    def __init__(self) -> None:
        self._state = SyncHealthState()

    @property
    def state(self) -> SyncHealthState:
        return self._state

    def record_success(self) -> None:
        self._state.healthy = True
        self._state.consecutive_failures = 0
        self._state.last_success_at = time.time()
        self._state.last_error = None
        self._state.warnings.clear()

    def record_failure(self, error: str) -> None:
        self._state.consecutive_failures += 1
        self._state.last_failure_at = time.time()
        self._state.last_error = error
        if self._state.consecutive_failures >= CONSECUTIVE_FAILURE_WARNING_THRESHOLD:
            self._state.healthy = False
            warning = (
                f"Sync loop has failed {self._state.consecutive_failures} consecutive times: {error}"
            )
            if warning not in self._state.warnings:
                self._state.warnings.append(warning)

    def record_master_pull(self, *, forced: bool, bytes_transferred: int, row_count: int = 0) -> None:
        self._state.last_master_pull_at = time.time()
        self._state.last_master_pull_bytes = bytes_transferred
        self._state.last_master_pull_forced = forced
        self._state.total_master_pull_bytes += bytes_transferred

    def set_quarantined_count(self, count: int) -> None:
        self._state.quarantined_rows = count

    def to_dict(self) -> dict[str, Any]:
        s = self._state
        return {
            "healthy": s.healthy,
            "consecutive_failures": s.consecutive_failures,
            "last_success_at": s.last_success_at,
            "last_failure_at": s.last_failure_at,
            "last_error": s.last_error,
            "last_master_pull_at": s.last_master_pull_at,
            "last_master_pull_bytes": s.last_master_pull_bytes,
            "last_master_pull_forced": s.last_master_pull_forced,
            "total_master_pull_bytes": s.total_master_pull_bytes,
            "quarantined_rows": s.quarantined_rows,
            "warnings": list(s.warnings),
        }


sync_health = SyncHealthTracker()
