"""
Enterprise Desktop Launcher
───────────────────────────
Features:
1. Singleton Instance Lock (prevent double opening).
2. Clean shutdown signal handling.
3. Automated uvicorn/webview lifecycle.
"""

import sys
import os
import time
import threading
import socket
import asyncio
import webbrowser
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Singleton Lock Check
_LOCK_PORT = 19283 # Arbitrary port for socket lock
_lock_socket = None
_auth_header_cache = None
_sync_lock = None
_order_query_cache = {}  # {query_hash: {"timestamp": float, "response": dict}}

def _is_already_running() -> bool:
    global _lock_socket
    try:
        _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _lock_socket.bind(("127.0.0.1", _LOCK_PORT))
        return False
    except socket.error:
        return True

# Ensure project root is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.environ["RUNTIME_MODE"] = "desktop"

from desktop.config import config
from desktop.logger import desktop_logger as log
from desktop.printer import thermal_printer

class JSAPI:
    """The bridge between JavaScript and Python."""
    def print_silent(self, html_content: str):
        """Queue exact frontend receipt HTML for silent printing."""
        log.info("Silent print requested from frontend.")
        try:
            return thermal_printer.print_html(html_content, document_name="frontend-receipt")
        except Exception as e:
            log.error(f"Native silent print failed: {e}")
            return False

def main():
    if _is_already_running():
        print("Application is already running.")
        sys.exit(0)

    log.info("Starting Top Chef Enterprise POS...")

    # 1. Splash
    from desktop.splash import splash
    splash.show()

    # 2. Local Server (Uvicorn)
    from app.main import app
    import uvicorn
    import asyncio
    import httpx
    import time
    from fastapi.responses import JSONResponse
    from starlette.middleware.base import BaseHTTPMiddleware

    # Global variables for caching and background sync
    global _sync_lock
    if _sync_lock is None:
        _sync_lock = asyncio.Lock()
        
    from app.core.sync import sync_manager
    from app.core.cloud_client import cloud_client
    from app.core.config import settings

    async def _desktop_sync_loop():
        """Background synchronization engine running constantly with outbox draining."""
        from app.core.database import AsyncSessionLocal
        from app.core.desktop_reconcile import apply_master_data_snapshot
        from sqlalchemy import select
        import platform
        
        device_id = config.device_id
        loop_counter = 0
        last_master_data_sync_at = None
        force_master_pull = True
        last_heartbeat_at = 0.0
        last_pull_at_mon = 0.0
        
        while True:
            from app.core.events import outbox_sync_trigger
            try:
                wait_timeout = 1.0 if force_master_pull else 60.0
                await asyncio.wait_for(outbox_sync_trigger.wait(), timeout=wait_timeout)
                outbox_sync_trigger.clear()
                # Wait briefly to let the DB transaction commit before querying Outbox
                await asyncio.sleep(0.2)
            except asyncio.TimeoutError:
                pass
            
            loop_counter += 1
            if not _auth_header_cache:
                continue
            
            async with _sync_lock:
                try:
                    from app.modules.orders.models import OutboxEvent, OutboxEventStatus
                    
                    async with AsyncSessionLocal() as db:
                        # 1. Drain Outbox
                        result = await db.execute(
                            select(OutboxEvent)
                            .where(OutboxEvent.status == OutboxEventStatus.PENDING)
                            .order_by(OutboxEvent.created_at.asc())
                            .limit(50)
                        )
                        pending_events = result.scalars().all()
                        
                        if pending_events:
                            payload = {
                                "device_id": device_id,
                                "events": [
                                    {
                                        "event_id": e.id,
                                        "event_type": e.event_type,
                                        "topic": e.topic,
                                        "payload": e.payload,
                                        "created_at": e.created_at.isoformat()
                                    }
                                    for e in pending_events
                                ]
                            }
                            
                            sync_result = await cloud_client.post_json("/desktop-updates/sync/events", payload)
                            accepted = int((sync_result or {}).get("accepted", 0))
                            rejected = int((sync_result or {}).get("rejected", 0))
                            errors = (sync_result or {}).get("errors", [])
                            if sync_result and rejected == 0 and accepted >= len(pending_events):
                                # Mark completed
                                from datetime import datetime, timezone, timedelta
                                for e in pending_events:
                                    e.status = OutboxEventStatus.COMPLETED
                                    e.processed_at = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)
                                await db.commit()
                                log.info(f"📤 Outbox: Successfully synced {len(pending_events)} events to cloud.")
                            else:
                                for e in pending_events:
                                    e.retry_count = (e.retry_count or 0) + 1
                                    if e.retry_count >= 5:
                                        e.status = OutboxEventStatus.FAILED
                                        e.error_message = "; ".join(errors[:3]) if errors else "Cloud did not accept the outbox batch"
                                await db.commit()
                                log.warning(
                                    "Outbox: cloud did not fully accept batch accepted=%s rejected=%s pending=%s errors=%s",
                                    accepted,
                                    rejected,
                                    len(pending_events),
                                    errors[:3],
                                )

                        # 2. Pull cloud authoritative data into the local database.
                        now_mon = time.monotonic()
                        should_pull = force_master_pull or (last_master_data_sync_at and (now_mon - last_pull_at_mon > 300))
                        
                        if should_pull:
                            params = {}
                            if last_master_data_sync_at:
                                params["since"] = last_master_data_sync_at

                            snapshot = await cloud_client.get("/desktop-updates/master-data", params=params)
                            if snapshot:
                                stats = await apply_master_data_snapshot(db, snapshot)
                                last_master_data_sync_at = snapshot.get("timestamp") or last_master_data_sync_at
                                force_master_pull = False
                                last_pull_at_mon = now_mon
                                changed = sum(stats.values())
                                if changed:
                                    log.info("Cloud reconciliation applied %s rows: %s", changed, stats)
                                    # Trigger local UI refresh if anything changed
                                    from app.core.events import order_events_manager
                                    await order_events_manager.broadcast_all({"type": "SYNC_COMPLETE", "stats": stats})
                            elif force_master_pull:
                                log.warning("Initial cloud reconciliation could not run; will retry on next sync tick.")

                        # 3. Periodic Heartbeat
                        if time.monotonic() - last_heartbeat_at >= 60:
                            heartbeat_payload = {
                                "device_id": device_id,
                                "version": settings.VERSION,
                                "os": platform.system()
                            }
                            if await cloud_client.post("/desktop-updates/sync/heartbeat", heartbeat_payload):
                                last_heartbeat_at = time.monotonic()

                        # 4. Global Counter Reset
                        if loop_counter >= 1200: # Reset every ~20 mins
                            loop_counter = 0
                                
                except Exception as e:
                    log.error(f"Desktop background sync loop failed: {e}")

    # Replace the existing lifespan with a wrapper that includes the desktop sync loop
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def desktop_lifespan(app: FastAPI):
        # 1. Start the desktop sync loop in the background
        sync_task = asyncio.create_task(_desktop_sync_loop())
        
        # 2. Run the original app lifespan
        async with original_lifespan(app):
            yield
            
        # 3. Cleanup
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass

    app.router.lifespan_context = desktop_lifespan

    class DesktopSyncMiddleware(BaseHTTPMiddleware):
        """
        Intercepts and suppresses redundant order GETs when WebSocket is active.
        Ensures Cloud is the source of truth for orders.
        """
        async def dispatch(self, request, call_next):
            path = request.url.path
            method = request.method
            
            # 1. Update Auth Cache
            auth_header = request.headers.get("authorization")
            if auth_header:
                global _auth_header_cache
                _auth_header_cache = auth_header
                cloud_client.update_token(auth_header)

            # 2. Poll Suppression & Redundancy Check
            if method == "GET" and sync_manager.suppress_poll(path):
                # Return cached response if available to avoid any traffic
                query_hash = f"cache_{path}_{request.query_params}"
                cache_entry = _order_query_cache.get(query_hash)
                
                if cache_entry and (time.time() - cache_entry["timestamp"]) < 10.0:
                    return JSONResponse(content=cache_entry["response"])
                
                # If it's a sync status request, return a lightweight "WS_ACTIVE" status
                if "/sync/status" in path:
                    status_data = {"status": "ok", "mode": "websocket", "syncing": True}
                    _order_query_cache[query_hash] = {"timestamp": time.time(), "response": status_data}
                    return JSONResponse(content=status_data)

            # 3. Cloud Proxy for Orders (Strict Source of Truth)
            if path in ("/orders/", "/orders") and method == "GET":
                source = request.query_params.get("source")
                if source in ("online", "OrderSource.ONLINE"):
                    params = dict(request.query_params)
                    json_data = await cloud_client.get("/orders/", params=params)
                    if json_data:
                        query_hash = f"cache_{path}_{request.query_params}"
                        _order_query_cache[query_hash] = {"timestamp": time.time(), "response": json_data}
                        return JSONResponse(content=json_data)

            return await call_next(request)

    app.add_middleware(DesktopSyncMiddleware)
    
    def _run_server():
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=config.local_port,
            log_level="info",
            ws_ping_interval=20,
            ws_ping_timeout=20,
        )

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # Wait for readiness
    import urllib.request

    app_url = f"http://127.0.0.1:{config.local_port}/"
    health_url = f"http://127.0.0.1:{config.local_port}/health"

    def _wait_for_server(timeout_seconds: int = 20) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(health_url, timeout=2) as response:
                    if 200 <= response.status < 500:
                        return True
            except Exception:
                time.sleep(0.5)
        return False

    if not _wait_for_server():
        log.error("Local API failed to become ready at %s", health_url)
        splash.close()
        return

    # 3. Tray
    from desktop.tray import tray_icon
    
    def _quit():
        log.info("Shutdown initiated...")
        os._exit(0)

    tray_icon.set_callbacks(
        on_show=lambda: None, # Handled by webview
        on_quit=_quit,
        on_sync=lambda: None,
        on_test_print=thermal_printer.test_print
    )
    tray_icon.start()

    # 4. UI Window (PyWebView)
    try:
        log.info("Launching desktop window via pywebview.")
        import webview
        splash.close()
        api = JSAPI()
        webview.create_window(
            "Top Chef POS",
            app_url,
            js_api=api,
            width=1280, height=800
        )
        log.info("Starting pywebview event loop.")
        webview.start(gui="edgechromium")
    except Exception as e:
        log.error(f"UI Failed: {e}")
        try:
            webbrowser.open(app_url)
            log.info("Fell back to default browser at %s", app_url)
        except Exception as browser_error:
            log.error("Browser fallback failed: %s", browser_error)
        _quit()

if __name__ == "__main__":
    main()
