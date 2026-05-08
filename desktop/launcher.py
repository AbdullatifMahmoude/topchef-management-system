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
        global _auth_header_cache
        try:
            log.info("⚙️ Sync: Background worker task started.")
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
            _last_sync_failure_at = None
            _sync_backoff_seconds = 5
            
            log.info("⚙️ Sync: Entering main loop...")
        except Exception as e:
            log.error(f"FATAL ERROR in _desktop_sync_loop initialization: {e}", exc_info=True)
            return
        while True:
            try:
                # Sleep briefly to avoid maxing out CPU but remain highly responsive
                await asyncio.sleep(1.0)
                
                from app.core.events import get_outbox_sync_trigger
                trigger = get_outbox_sync_trigger()
                
                if trigger.is_set():
                    log.info("🔄 Sync: Worker woke up (trigger set).")
                    trigger.clear()
                    force_master_pull = True
                    # Wait briefly to let any DB transactions commit before querying Outbox
                    await asyncio.sleep(0.2)
                elif force_master_pull:
                    # if force_master_pull is true, we don't need to wait for trigger
                    pass
            except Exception as e:
                log.error(f"Error checking sync trigger: {e}")
                pass
            
            loop_counter += 1
            if not _auth_header_cache:
                if loop_counter % 10 == 0:
                    log.info("Outbox: Waiting for user activity to capture Auth header...")
                continue

            # Handle network backoff
            if _last_sync_failure_at:
                seconds_since_failure = (asyncio.get_event_loop().time() - _last_sync_failure_at)
                if seconds_since_failure < _sync_backoff_seconds:
                    continue
            
            # If we just got the token and haven't synced yet, force a pull
            if last_master_data_sync_at is None:
                force_master_pull = True
            
            # Lazy initialize the sync lock in the correct loop
            global _sync_lock
            if _sync_lock is None:
                _sync_lock = asyncio.Lock()
                
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
                            log.info(f"📤 Outbox: Found {len(pending_events)} pending events. Syncing...")
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
                            log.info(f"Outbox: Cloud response: {sync_result}")
                            accepted = int((sync_result or {}).get("accepted", 0))
                            rejected = int((sync_result or {}).get("rejected", 0))
                            errors = (sync_result or {}).get("errors", [])
                            
                            from datetime import datetime, timezone, timedelta
                            now_ts = datetime.now(timezone(timedelta(hours=3))).replace(tzinfo=None)

                            if sync_result:
                                # Mark the number of events the cloud actually accepted as COMPLETED
                                for i in range(min(accepted, len(pending_events))):
                                    e = pending_events[i]
                                    e.status = OutboxEventStatus.COMPLETED
                                    e.processed_at = now_ts
                                
                                # Mark the specific ones rejected as FAILED if there's a permanent error
                                # Otherwise they stay PENDING to be retried (or handled by retry_count logic)
                                for i in range(accepted, min(accepted + rejected, len(pending_events))):
                                    e = pending_events[i]
                                    e.status = OutboxEventStatus.FAILED
                                    e.error_message = errors[i - accepted] if (i - accepted) < len(errors) else "Rejected by cloud"
                                    e.processed_at = now_ts

                                # Logic for remaining pending events (transient issues)
                                for i in range(accepted + rejected, len(pending_events)):
                                    e = pending_events[i]
                                    e.retry_count = (e.retry_count or 0) + 1
                                    if e.retry_count >= 5:
                                        e.status = OutboxEventStatus.FAILED
                                        e.error_message = "Cloud did not accept after 5 retries"
                                        e.processed_at = now_ts

                                await db.commit()
                                if accepted > 0:
                                    log.info(f"📤 Outbox: Successfully synced {accepted} events to cloud.")
                                    # Reset backoff on success
                                    _last_sync_failure_at = None
                                    _sync_backoff_seconds = 5
                                if rejected > 0:
                                    log.warning(f"⚠️ Outbox: {rejected} events were rejected by cloud.")
                            else:
                                # Total failure (network error, etc.) 
                                # We stay PENDING because we want to retry when internet is back.
                                _last_sync_failure_at = asyncio.get_event_loop().time()
                                # Exponential backoff up to 60 seconds
                                _sync_backoff_seconds = min(_sync_backoff_seconds * 2, 60)
                                
                                for e in pending_events:
                                    e.retry_count = (e.retry_count or 0) + 1
                                    if e.retry_count >= 100: # Very high limit for network errors
                                        e.status = OutboxEventStatus.FAILED
                                        e.error_message = "Persistent network failure (100 retries)"
                                        e.processed_at = now_ts
                                await db.commit()
                                log.warning(
                                    "Outbox: cloud unreachable (backoff=%ds). Batch stays PENDING.",
                                    _sync_backoff_seconds
                                )
                                force_master_pull = True

                        # 2. Pull cloud authoritative data into the local database.
                        now_mon = time.monotonic()
                        # If we have no last sync time, always pull.
                        if not last_master_data_sync_at:
                            force_master_pull = True
                            
                        should_pull = force_master_pull or (last_master_data_sync_at and (now_mon - last_pull_at_mon > 120))
                        
                        if should_pull:
                            log.info("📥 Sync: Pulling master data from cloud (forced=%s)...", force_master_pull)
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
        log.info("🚀 Sync: Lifespan initiated...")
        # 1. Start the desktop sync loop in the background
        sync_task = asyncio.create_task(_desktop_sync_loop())
        
        # 2. Run the original app lifespan
        log.info("🚀 Sync: Running original app lifespan...")
        async with original_lifespan(app):
            yield
            
        # 3. Cleanup
        log.info("🚀 Sync: Cleaning up...")
        sync_task.cancel()
        try:
            await sync_task
        except asyncio.CancelledError:
            pass

    app.router.lifespan_context = desktop_lifespan

    class DesktopSyncMiddleware:
        """
        Pure ASGI middleware to intercept and suppress redundant order GETs when WebSocket is active.
        Ensures Cloud is the source of truth for orders without breaking WebSocket handshakes.
        """
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await self.app(scope, receive, send)

            path = scope.get("path", "")
            method = scope.get("method", "")
            
            # 1. Update Auth Cache
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization", b"").decode("utf-8")
            if auth_header:
                global _auth_header_cache
                was_empty = (_auth_header_cache is None)
                _auth_header_cache = auth_header
                cloud_client.update_token(auth_header)
                log.info("🔑 Auth: Captured credentials from request.")
                
                # If we just got a token, wake up the sync loop immediately
                if was_empty:
                    from app.core.events import get_outbox_sync_trigger
                    get_outbox_sync_trigger().set()

            # 2. Poll Suppression & Redundancy Check
            from fastapi.responses import JSONResponse
            if method == "GET" and sync_manager.suppress_poll(path):
                query_string = scope.get("query_string", b"").decode("utf-8")
                
                # NEVER cache online order queries - they must always go to the cloud proxy
                # for accurate statuses (cloud is the source of truth for online orders)
                if "source=online" in query_string:
                    pass  # Skip cache, let it fall through to the cloud proxy below
                else:
                    query_hash = f"cache_{path}_{query_string}"
                    cache_entry = _order_query_cache.get(query_hash)
                    
                    if cache_entry and (time.time() - cache_entry["timestamp"]) < 10.0:
                        response = JSONResponse(content=cache_entry["response"])
                        await response(scope, receive, send)
                        return
                    
                    # If it's a sync status request, return a lightweight "WS_ACTIVE" status
                    if "/sync/status" in path:
                        status_data = {"status": "ok", "mode": "websocket", "syncing": True}
                        _order_query_cache[query_hash] = {"timestamp": time.time(), "response": status_data}
                        response = JSONResponse(content=status_data)
                        await response(scope, receive, send)
                        return

            # 3. Cloud Proxy for Orders (Source of Truth for ONLINE orders only)
            if path in ("/orders/", "/orders") and method == "GET":
                # Parse query string for source
                from urllib.parse import parse_qs
                query_string = scope.get("query_string", b"").decode("utf-8")
                params = parse_qs(query_string)
                source_list = params.get("source", [])
                source = source_list[0] if source_list else None
                
                # Only proxy to cloud for ONLINE orders (cloud is the source of truth)
                # For CASHIER orders, use local SQLite (desktop is the source of truth)
                if source != "cashier":
                    flat_params = {k: v[0] for k, v in params.items()}
                    json_data = await cloud_client.get("/orders/", params=flat_params)
                    if json_data:
                        query_hash = f"cache_{path}_{query_string}"
                        _order_query_cache[query_hash] = {"timestamp": time.time(), "response": json_data}
                        response = JSONResponse(content=json_data)
                        await response(scope, receive, send)
                        return
                # If source=cashier or cloud fails, fall through to local handler

            # 4. Cloud Proxy for Order Updates (PATCH) and Details (GET)
            # If the order is not found locally, it must be a cloud order we are currently viewing
            # via the proxy above. We must proxy the request back to the cloud.
            if method in ("PATCH", "GET") and path.startswith("/orders/"):
                parts = path.strip("/").split("/")
                # Match /orders/{id} or /orders/{id}/status
                if len(parts) >= 2 and parts[0] == "orders" and parts[1].isdigit():
                    try:
                        order_id = int(parts[1])
                        from app.core.database import AsyncSessionLocal
                        from sqlalchemy import select
                        from app.modules.orders.models import Order
                        
                        async with AsyncSessionLocal() as db_session:
                            exists = await db_session.scalar(select(Order.id).where(Order.id == order_id))
                        
                        if not exists:
                            log.info(f"🚀 Proxy: Order {order_id} not found locally. Proxying {method} to cloud...")
                            
                            if method == "PATCH":
                                from starlette.requests import Request
                                req = Request(scope, receive)
                                try:
                                    json_data = await req.json()
                                except:
                                    json_data = {}
                                res_data = await cloud_client.patch(path, json_data)
                            else:
                                # GET - parse query params if any
                                from urllib.parse import parse_qs
                                query_string = scope.get("query_string", b"").decode("utf-8")
                                params = parse_qs(query_string)
                                flat_params = {k: v[0] for k, v in params.items()}
                                res_data = await cloud_client.get(path, params=flat_params)

                            if res_data:
                                response = JSONResponse(content=res_data)
                                await response(scope, receive, send)
                                return
                            else:
                                # If cloud also fails or returns None, return 404 as fallback
                                response = JSONResponse(status_code=404, content={"detail": f"Order {order_id} not found on local or cloud"})
                                await response(scope, receive, send)
                                return
                    except (ValueError, IndexError):
                        pass

            return await self.app(scope, receive, send)

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
