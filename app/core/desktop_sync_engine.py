"""Desktop background sync engine — outbox drain, incremental master-data pull, backoff."""

from __future__ import annotations

import asyncio
import json
import platform
import random
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, literal, select

from app.core.cloud_client import cloud_client
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.desktop_reconcile import apply_master_data_snapshot, count_quarantined_rows
from app.core.events import get_outbox_sync_trigger
from app.core.sync_health import CONSECUTIVE_FAILURE_WARNING_THRESHOLD, sync_health
from app.core.sync_triggers import consume_force_master_pull, request_force_master_pull, consume_incremental_pull
from app.modules.orders.models import OutboxEvent, OutboxEventStatus

MASTER_DATA_INTERVAL_SECONDS = 120
INITIAL_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 300  # 5 minutes


def compute_backoff_seconds(current: float, *, success: bool = False) -> float:
    """Exponential backoff with jitter, capped at MAX_BACKOFF_SECONDS."""
    if success:
        return INITIAL_BACKOFF_SECONDS
    next_backoff = min(current * 2, MAX_BACKOFF_SECONDS)
    jitter = random.uniform(0, min(next_backoff * 0.1, 30))
    return next_backoff + jitter


def master_data_params(*, force_full: bool, last_sync_at: datetime | None) -> dict:
    """Build query params for master-data pull. Full pull omits `since`."""
    if force_full or last_sync_at is None:
        return {}
    return {"since": (last_sync_at - timedelta(seconds=5)).isoformat()}


def estimate_snapshot_bytes(snapshot: dict | None) -> int:
    if not snapshot:
        return 0
    try:
        return len(json.dumps(snapshot, default=str).encode("utf-8"))
    except Exception:
        return 0


async def run_desktop_sync_loop(
    *,
    device_id: str,
    auth_header_getter,
    log,
) -> None:
    """
    Background synchronization engine.
    auth_header_getter: callable returning the cached Authorization header or None.
    """
    loop_counter = 0
    last_master_data_sync_at: datetime | None = None
    force_master_pull = True  # first-run full pull
    last_heartbeat_at = 0.0
    last_pull_at_mon = 0.0
    last_sync_failure_at: float | None = None
    sync_backoff_seconds = float(INITIAL_BACKOFF_SECONDS)

    log.info("Sync: Background worker task started.")
    log.info("Sync: Entering main loop...")

    while True:
        try:
            trigger = get_outbox_sync_trigger()
            try:
                await asyncio.wait_for(trigger.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass

            if trigger.is_set():
                log.info("Sync: Worker woke up (outbox trigger).")
                trigger.clear()
                await asyncio.sleep(0.2)

            if consume_force_master_pull():
                force_master_pull = True
                log.info("Sync: Force master-data pull requested.")

            if consume_incremental_pull():
                last_pull_at_mon = 0.0
                log.info("Sync: Incremental master-data pull requested.")

        except Exception as exc:
            log.error("Error checking sync trigger: %s", exc)

        loop_counter += 1
        auth_header = auth_header_getter()
        if not auth_header or not cloud_client.is_authenticated():
            if loop_counter % 10 == 0:
                log.info("Outbox: Waiting for user activity to capture Auth header...")
            continue

        if last_sync_failure_at is not None:
            elapsed = asyncio.get_event_loop().time() - last_sync_failure_at
            if elapsed < sync_backoff_seconds:
                continue

        try:
            async with AsyncSessionLocal() as db:
                event_priority = case(
                    (OutboxEvent.event_type == "CUSTOMER_CREATED", literal(0)),
                    (OutboxEvent.event_type == "ADDRESS_CREATED", literal(1)),
                    (OutboxEvent.event_type == "ORDER_CREATED", literal(2)),
                    (OutboxEvent.event_type == "SHIFT_CREATED", literal(2)),
                    (OutboxEvent.event_type == "SHIFT_UPDATED", literal(2)),
                    else_=literal(3),
                )
                result = await db.execute(
                    select(OutboxEvent)
                    .where(OutboxEvent.status == OutboxEventStatus.PENDING)
                    .order_by(event_priority, OutboxEvent.created_at.asc())
                    .limit(50)
                )
                pending_events = result.scalars().all()

                if pending_events:
                    log.info("Outbox: Found %s pending events. Syncing...", len(pending_events))
                    payload = {
                        "device_id": device_id,
                        "events": [
                            {
                                "event_id": e.id,
                                "event_type": e.event_type,
                                "topic": e.topic,
                                "payload": e.payload,
                                "created_at": e.created_at.isoformat(),
                            }
                            for e in pending_events
                        ],
                    }

                    sync_result = await cloud_client.post_json("/desktop-updates/sync/events", payload)
                    log.info("Outbox: Cloud response: %s", sync_result)
                    accepted = int((sync_result or {}).get("accepted", 0))
                    rejected = int((sync_result or {}).get("rejected", 0))
                    accepted_ids = {
                        int(event_id) for event_id in (sync_result or {}).get("accepted_event_ids", [])
                    }
                    errors = (sync_result or {}).get("errors", [])
                    now_ts = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)

                    if sync_result:
                        for e in pending_events:
                            if e.id not in accepted_ids:
                                continue
                            e.status = OutboxEventStatus.COMPLETED
                            e.processed_at = now_ts

                        for e in pending_events:
                            if e.id not in accepted_ids:
                                e.retry_count = (e.retry_count or 0) + 1
                                if errors:
                                    e.error_message = "; ".join(map(str, errors))[:2000]

                        await db.commit()
                        if accepted > 0:
                            log.info("Outbox: Successfully synced %s events to cloud.", accepted)
                            last_sync_failure_at = None
                            sync_backoff_seconds = float(INITIAL_BACKOFF_SECONDS)
                            sync_health.record_success()
                        if rejected > 0:
                            log.warning("Outbox: %s events were rejected by cloud.", rejected)
                    else:
                        last_sync_failure_at = asyncio.get_event_loop().time()
                        sync_backoff_seconds = compute_backoff_seconds(sync_backoff_seconds)
                        sync_health.record_failure("Outbox cloud unreachable")

                        for e in pending_events:
                            e.retry_count = (e.retry_count or 0) + 1
                        await db.commit()
                        log.warning(
                            "Outbox: cloud unreachable (backoff=%.0fs). Batch stays PENDING.",
                            sync_backoff_seconds,
                        )
                        if sync_health.state.consecutive_failures >= CONSECUTIVE_FAILURE_WARNING_THRESHOLD:
                            log.warning(
                                "SYNC HEALTH: %s consecutive failures — last error: %s",
                                sync_health.state.consecutive_failures,
                                sync_health.state.last_error,
                            )
                        continue

                now_mon = time.monotonic()
                periodic_due = (now_mon - last_pull_at_mon) >= MASTER_DATA_INTERVAL_SECONDS
                should_pull = force_master_pull or periodic_due

                if should_pull:
                    is_forced = force_master_pull
                    params = master_data_params(force_full=is_forced, last_sync_at=last_master_data_sync_at)
                    log.info(
                        "Sync: Pulling master data from cloud (forced=%s, incremental=%s)...",
                        is_forced,
                        bool(params.get("since")),
                    )

                    snapshot = await cloud_client.get("/desktop-updates/master-data", params=params)
                    bytes_transferred = cloud_client.last_response_bytes or estimate_snapshot_bytes(snapshot)

                    if snapshot:
                        try:
                            stats = await apply_master_data_snapshot(db, snapshot)
                            quarantined = await count_quarantined_rows(db)
                            sync_health.set_quarantined_count(quarantined)

                            cloud_timestamp = snapshot.get("timestamp")
                            if cloud_timestamp:
                                if isinstance(cloud_timestamp, str):
                                    last_master_data_sync_at = datetime.fromisoformat(
                                        cloud_timestamp.replace("Z", "+00:00")
                                    )
                                else:
                                    last_master_data_sync_at = cloud_timestamp

                            force_master_pull = False
                            last_pull_at_mon = now_mon
                            last_sync_failure_at = None
                            sync_backoff_seconds = float(INITIAL_BACKOFF_SECONDS)
                            sync_health.record_success()

                            row_count = sum(stats.values())
                            sync_health.record_master_pull(
                                forced=is_forced,
                                bytes_transferred=bytes_transferred,
                                row_count=row_count,
                            )
                            log.info(
                                "Sync: master-data pull complete — %s rows changed, ~%s KB transferred (forced=%s)",
                                row_count,
                                round(bytes_transferred / 1024, 1),
                                is_forced,
                            )

                            if row_count:
                                log.info("Cloud reconciliation applied %s rows: %s", row_count, stats)
                                from app.core.events import order_events_manager
                                await order_events_manager.broadcast_all(
                                    {"type": "SYNC_COMPLETE", "stats": stats}
                                )
                        except Exception as reconcile_exc:
                            last_sync_failure_at = asyncio.get_event_loop().time()
                            sync_backoff_seconds = compute_backoff_seconds(sync_backoff_seconds)
                            sync_health.record_failure(str(reconcile_exc))
                            log.error(
                                "Master-data reconcile failed (backoff=%.0fs): %s",
                                sync_backoff_seconds,
                                reconcile_exc,
                                exc_info=True,
                            )
                            if sync_health.state.consecutive_failures >= CONSECUTIVE_FAILURE_WARNING_THRESHOLD:
                                log.warning(
                                    "SYNC HEALTH: %s consecutive failures — investigate sync_quarantine table",
                                    sync_health.state.consecutive_failures,
                                )
                    elif is_forced:
                        log.warning(
                            "Initial cloud reconciliation failed (cloud unreachable); will retry with backoff."
                        )
                        last_sync_failure_at = asyncio.get_event_loop().time()
                        sync_backoff_seconds = compute_backoff_seconds(sync_backoff_seconds)
                        sync_health.record_failure("Initial master-data pull unreachable")
                        last_pull_at_mon = now_mon
                        force_master_pull = False

                if auth_header and time.monotonic() - last_heartbeat_at >= 60:
                    heartbeat_payload = {
                        "device_id": device_id,
                        "version": settings.VERSION,
                        "os": platform.system(),
                    }
                    await cloud_client.post("/desktop-updates/sync/heartbeat", heartbeat_payload)
                    last_heartbeat_at = time.monotonic()

                if loop_counter >= 1200:
                    loop_counter = 0

        except Exception as exc:
            last_sync_failure_at = asyncio.get_event_loop().time()
            sync_backoff_seconds = compute_backoff_seconds(sync_backoff_seconds)
            sync_health.record_failure(str(exc))
            log.error("Desktop background sync loop failed (backoff=%.0fs): %s", sync_backoff_seconds, exc)
            if sync_health.state.consecutive_failures >= CONSECUTIVE_FAILURE_WARNING_THRESHOLD:
                log.warning(
                    "SYNC HEALTH: sync loop unhealthy after %s consecutive failures",
                    sync_health.state.consecutive_failures,
                )
