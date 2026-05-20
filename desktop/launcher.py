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
from pathlib import Path

# Redirect stdout/stderr to log file in windowed mode to prevent crashes and capture errors
if getattr(sys, 'frozen', False):
    try:
        _base = Path(sys.executable).parent
        _logs_dir = _base / "desktop" / "logs"
        _logs_dir.mkdir(parents=True, exist_ok=True)
        _err_log = open(_logs_dir / "desktop_errors.log", "a", encoding="utf-8")
        sys.stdout = _err_log
        sys.stderr = _err_log
    except Exception:
        if sys.stdout is None: sys.stdout = open(os.devnull, "w")
        if sys.stderr is None: sys.stderr = open(os.devnull, "w")
else:
    if sys.stdout is None: sys.stdout = open(os.devnull, "w")
    if sys.stderr is None: sys.stderr = open(os.devnull, "w")
import time
import threading
import socket
import asyncio
import webbrowser
import faulthandler
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

from desktop.config import config, DATA_DIR
from desktop.logger import desktop_logger as log
from desktop.printer import thermal_printer

class JSAPI:
    """The bridge between JavaScript and Python."""
    def print_silent(self, html_content: str, order_data: dict = None):
        """Queue exact frontend receipt HTML for silent printing."""
        log.info("Silent print requested from frontend.")
        try:
            return thermal_printer.print_html(html_content, document_name="frontend-receipt", order_data=order_data)
        except Exception as e:
            log.error(f"Native silent print failed: {e}")
            return False

    def zoom_in(self):
        """Increase zoom by 10%."""
        level = min(config.get("zoom_level", 100) + 10, 200)
        config.set("zoom_level", level)
        config.save()
        return level

    def zoom_out(self):
        """Decrease zoom by 10%."""
        level = max(config.get("zoom_level", 100) - 10, 50)
        config.set("zoom_level", level)
        config.save()
        return level

    def zoom_reset(self):
        """Reset zoom to 100%."""
        config.set("zoom_level", 100)
        config.save()
        return 100

    def set_zoom(self, level: int):
        """Set zoom to a specific level (50-200)."""
        level = max(50, min(200, int(level)))
        config.set("zoom_level", level)
        config.save()
        return level

    def get_zoom(self):
        """Get current zoom level."""
        return config.get("zoom_level", 100)

CURRENT_VERSION = "1.0.0"

async def check_for_updates():
    """Checks the cloud for a newer desktop version and handles auto-update."""
    if not getattr(sys, 'frozen', False):
        # Don't try to auto-update when running as a python script (development)
        return None

    try:
        import httpx
        import subprocess
        from app.core.cloud_client import cloud_client
        
        # 1. Check Version
        res = await cloud_client.get("/desktop-updates/version")
        if not res or not res.get("version") or res.get("version") <= CURRENT_VERSION:
            return None

        new_version = res.get("version")
        download_url = res.get("download_url") or f"{cloud_client.base_url}/desktop-updates/download"
        
        log.info(f"🚀 New version found: {new_version}. Starting auto-update...")

        # 2. Download to Temp File
        current_exe = sys.executable
        temp_exe = current_exe + ".new"
        
        async with httpx.AsyncClient(timeout=300.0) as client:
            async with client.stream("GET", download_url) as response:
                if response.status_code != 200:
                    log.error(f"Failed to download update: {response.status_code}")
                    return None
                with open(temp_exe, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

        log.info("📥 Update downloaded. Applying...")

        # 3. Create Updater Batch Script
        # This script waits for the app to close, replaces the EXE, restarts it, and deletes itself.
        updater_bat = os.path.join(os.path.dirname(current_exe), "updater.bat")
        with open(updater_bat, "w", encoding="cp1252") as f:
            f.write(f"""@echo off
timeout /t 2 /nobreak > nul
move /y "{temp_exe}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
""")

        # 4. Launch Updater and Exit
        subprocess.Popen([updater_bat], shell=True)
        log.info("👋 Restarting app to apply update...")
        os._exit(0)

    except Exception as e:
        log.error(f"Auto-update failed: {e}", exc_info=True)
    return None

def main():
    if _is_already_running():
        print("Application is already running.")
        sys.exit(0)

    log.info(f"Starting Top Chef Enterprise POS [v{CURRENT_VERSION}]...")

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
    # Lock is lazily initialized inside the event loop in _desktop_sync_loop
        
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
            
            # Lazy initialize the sync lock in the correct loop
            global _sync_lock
            if _sync_lock is None:
                _sync_lock = asyncio.Lock()
                
            async with _sync_lock:
                try:
                    from app.modules.orders.models import OutboxEvent, OutboxEventStatus
                    
                    async with AsyncSessionLocal() as db:
                        # 1. Drain Outbox — dependency-aware ordering:
                        #    0: CUSTOMER_CREATED  (customer must exist first)
                        #    1: ADDRESS_CREATED   (address needs customer)
                        #    2: ORDER_CREATED     (order needs customer + address)
                        #    3: everything else   (updates need their parent entity)
                        from sqlalchemy import case, literal
                        event_priority = case(
                            (OutboxEvent.event_type == 'CUSTOMER_CREATED', literal(0)),
                            (OutboxEvent.event_type == 'ADDRESS_CREATED',  literal(1)),
                            (OutboxEvent.event_type == 'ORDER_CREATED',    literal(2)),
                            else_=literal(3)
                        )
                        result = await db.execute(
                            select(OutboxEvent)
                            .where(OutboxEvent.status == OutboxEventStatus.PENDING)
                            .order_by(event_priority, OutboxEvent.created_at.asc())
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

                        now_mon = time.monotonic()
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
                                log.warning("Initial cloud reconciliation failed (cloud unreachable); will retry in 30s.")
                                # Reset force flag but set last_pull to a value that triggers retry in 30s
                                # 120s (normal interval) - 30s (retry delay) = 90s offset
                                last_pull_at_mon = now_mon - 90 
                                force_master_pull = False

                        # 3. Periodic Heartbeat (only if we have auth)
                        if _auth_header_cache and time.monotonic() - last_heartbeat_at >= 60:
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

    # Robustly wrap the app lifespan to include the desktop sync loop
    # We use a wrapper instead of replacing the property to ensure we capture the correct context
    original_lifespan = app.router.lifespan_context
    
    @asynccontextmanager
    async def desktop_lifespan_wrapper(app: FastAPI):
        log.info("🚀 Sync: Desktop lifespan wrapper started.")
        
        # 1. Run the original app lifespan FIRST to handle migrations and DB setup
        log.info("🚀 Sync: Entering original app lifespan...")
        async with original_lifespan(app):
            log.info("🚀 Sync: Original lifespan entered successfully. Starting background tasks...")
            
            # 2. Start the desktop sync loop ONLY after the original lifespan has 
            # established its context and verified the database.
            sync_task = asyncio.create_task(_desktop_sync_loop(), name="desktop-sync-worker")
            
            yield
            
            # 3. Cleanup
            log.info("🚀 Sync: Cleaning up desktop tasks...")
            sync_task.cancel()
            try:
                await sync_task
            except asyncio.CancelledError:
                pass
            log.info("🚀 Sync: Desktop tasks cleaned up.")

    app.router.lifespan_context = desktop_lifespan_wrapper

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
        try:
            # We pass log_config=None to prevent uvicorn from overriding our custom logging
            # which is already configured to write to desktop.log and capture stdout/stderr
            uvicorn.run(
                app,
                host="127.0.0.1",
                port=config.local_port,
                log_level="info",
                log_config=None, 
                ws_ping_interval=20,
                ws_ping_timeout=20,
            )
        except Exception as e:
            log.error(f"Uvicorn server crashed: {e}", exc_info=True)

    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # Wait for readiness
    import urllib.request

    app_url = f"http://127.0.0.1:{config.local_port}/"
    health_url = f"http://127.0.0.1:{config.local_port}/health"

    def _wait_for_server(timeout_seconds: int = 60) -> bool:
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

    # Background update check
    def run_update_check():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        update_info = loop.run_until_complete(check_for_updates())
        if update_info:
            # You can add a window notification here later if needed
            pass
            
    threading.Thread(target=run_update_check, daemon=True).start()

    # 3. Tray
    from desktop.tray import tray_icon
    
    def _quit():
        log.info("Shutdown initiated...")
        os._exit(0)

    tray_started = threading.Event()

    def _start_tray_once():
        if tray_started.is_set():
            return
        tray_started.set()
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
        webview_ready = threading.Event()
        watchdog_started_at = time.time()

        def _webview_watchdog():
            if webview_ready.wait(20):
                return
            log.error(
                "PyWebView did not report a loaded window within %.1fs; opening browser fallback at %s",
                time.time() - watchdog_started_at,
                app_url,
            )
            try:
                faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
            except Exception:
                pass
            try:
                webbrowser.open(app_url)
                log.info("Browser fallback opened while native WebView is unresponsive.")
            except Exception as browser_error:
                log.error("Browser fallback failed: %s", browser_error)

        threading.Thread(target=_webview_watchdog, daemon=True, name="webview-watchdog").start()

        import webview
        log.info("PyWebView imported successfully.")
        splash.close()
        api = JSAPI()
        window = webview.create_window(
            "Top Chef POS",
            app_url,
            js_api=api,
            width=1280, height=800,
            background_color="#0f0f0f",
            focus=True,
        )
        log.info("PyWebView window object created.")

        def _inject_zoom():
            """Inject zoom JS with multiple targets and retry logic."""
            try:
                saved_zoom = config.get("zoom_level", 100)
                zoom_js = """
                (function() {
                    console.log("Applying zoom: __ZOOM__%");
                    var apply = function(level) {
                        level = Math.max(50, Math.min(200, level));
                        var val = level + '%';
                        document.documentElement.style.zoom = val;
                        if (document.body) document.body.style.zoom = val;
                        
                        if (window.pywebview && window.pywebview.api) {
                            window.pywebview.api.set_zoom(level);
                        }
                        return level;
                    };

                    // Initial apply
                    apply(__ZOOM__);

                    if (window.__zoomInitialized) return;
                    window.__zoomInitialized = true;

                    document.addEventListener('keydown', function(e) {
                        if (!e.ctrlKey) return;
                        var current = parseInt(document.documentElement.style.zoom || '100');
                        if (e.key === '+' || e.key === '=' || e.code === 'Equal') {
                            e.preventDefault();
                            apply(current + 10);
                        } else if (e.key === '-' || e.code === 'Minus') {
                            e.preventDefault();
                            apply(current - 10);
                        } else if (e.key === '0' || e.code === 'Digit0') {
                            e.preventDefault();
                            apply(100);
                        }
                    });

                    document.addEventListener('wheel', function(e) {
                        if (!e.ctrlKey) return;
                        e.preventDefault();
                        var current = parseInt(document.documentElement.style.zoom || '100');
                        var delta = e.deltaY < 0 ? 10 : -10;
                        apply(current + delta);
                    }, {passive: false});
                })();
                """.replace("__ZOOM__", str(saved_zoom))
                window.evaluate_js(zoom_js)
                log.info("Zoom injected successfully at %d%%", saved_zoom)
                webview_ready.set()
                return True
            except Exception as e:
                log.warning("Zoom injection failed: %s", e)
                return False

        def _on_loaded():
            webview_ready.set()
            _inject_zoom()

        # Register event
        window.events.loaded += _on_loaded

        def _on_shown():
            """Bring window to foreground, disable always-on-top, and force zoom injection."""
            import time
            _start_tray_once()
            
            # Aggressive retry for zoom injection
            for i in range(5):
                if _inject_zoom():
                    break
                time.sleep(1.0)

        log.info("Starting pywebview event loop.")
        webview.start(
            gui="edgechromium",
            func=_on_shown,
            private_mode=False,
            storage_path=str(DATA_DIR / "webview_profile"),
        )
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
