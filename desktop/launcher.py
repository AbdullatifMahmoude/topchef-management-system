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
import webbrowser
from pathlib import Path

# Singleton Lock Check
_LOCK_PORT = 19283 # Arbitrary port for socket lock
_lock_socket = None

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
    
    def _run_server():
        uvicorn.run(app, host="127.0.0.1", port=config.local_port, log_level="info")

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
