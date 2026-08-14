"""Desktop sync trigger flags — separate outbox wake from forced master-data pull."""

_force_master_pull_requested: bool = False
_incremental_pull_requested: bool = False


def request_force_master_pull() -> None:
    """Request a full master-data pull on the next sync cycle (manual refresh / first run)."""
    global _force_master_pull_requested
    _force_master_pull_requested = True


def request_incremental_pull() -> None:
    """Request an incremental master-data pull on the next sync cycle (reconnect catch-up)."""
    global _incremental_pull_requested
    _incremental_pull_requested = True


def consume_force_master_pull() -> bool:
    """Return True once if a forced master-data pull was requested."""
    global _force_master_pull_requested
    if _force_master_pull_requested:
        _force_master_pull_requested = False
        return True
    return False


def consume_incremental_pull() -> bool:
    """Return True once if an incremental pull was requested."""
    global _incremental_pull_requested
    if _incremental_pull_requested:
        _incremental_pull_requested = False
        return True
    return False


def peek_force_master_pull() -> bool:
    return _force_master_pull_requested
