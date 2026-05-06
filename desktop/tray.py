"""
System Tray Icon
────────────────
Runs in the background using pystray.  Provides quick access to
show/hide the window, force sync, test print, and quit.
"""

import threading
from typing import Callable, Optional

from desktop.config import config
from desktop.logger import desktop_logger as log

# pystray + PIL are required
try:
    import pystray
    from PIL import Image, ImageDraw
    _HAS_TRAY = True
except ImportError:
    _HAS_TRAY = False
    log.warning("pystray/Pillow not installed – tray icon disabled")


def _create_default_icon(size: int = 64) -> "Image.Image":
    """Generate a simple coloured icon when no asset is available."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Orange circle with "TC" text
    draw.ellipse([2, 2, size - 2, size - 2], fill="#FF6B35")
    try:
        draw.text((size // 4, size // 4), "TC", fill="white")
    except Exception:
        pass
    return img


class TrayIcon:
    """System tray manager."""

    def __init__(self):
        self._icon: Optional[pystray.Icon] = None
        self._on_show: Optional[Callable] = None
        self._on_quit: Optional[Callable] = None
        self._on_sync: Optional[Callable] = None
        self._on_test_print: Optional[Callable] = None

    def set_callbacks(
        self,
        on_show: Callable = None,
        on_quit: Callable = None,
        on_sync: Callable = None,
        on_test_print: Callable = None,
    ):
        self._on_show = on_show
        self._on_quit = on_quit
        self._on_sync = on_sync
        self._on_test_print = on_test_print

    def start(self):
        if not _HAS_TRAY:
            log.warning("Tray icon not available")
            return

        icon_img = self._load_icon()
        menu = pystray.Menu(
            pystray.MenuItem("فتح التطبيق / Show", self._show, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("مزامنة الآن / Sync Now", self._sync),
            pystray.MenuItem("طباعة تجريبية / Test Print", self._test_print),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("إغلاق / Quit", self._quit),
        )

        self._icon = pystray.Icon("topchef", icon_img, "Top Chef POS", menu)
        threading.Thread(target=self._icon.run, daemon=True, name="tray-icon").start()
        log.info("Tray icon started")

    def stop(self):
        if self._icon:
            try:
                self._icon.stop()
            except Exception:
                pass

    def notify(self, title: str, message: str):
        if self._icon:
            try:
                self._icon.notify(message, title)
            except Exception as exc:
                log.debug("Tray notify failed: %s", exc)

    # ── Menu callbacks ────────────────────────────

    def _show(self, icon=None, item=None):
        if self._on_show:
            self._on_show()

    def _quit(self, icon=None, item=None):
        if self._on_quit:
            self._on_quit()

    def _sync(self, icon=None, item=None):
        if self._on_sync:
            self._on_sync()

    def _test_print(self, icon=None, item=None):
        if self._on_test_print:
            self._on_test_print()

    # ── Icon loading ──────────────────────────────

    def _load_icon(self) -> "Image.Image":
        from desktop.config import ASSETS_DIR
        icon_path = ASSETS_DIR / "icon.png"
        if icon_path.exists():
            try:
                return Image.open(icon_path)
            except Exception:
                pass
        return _create_default_icon()


# Module‑level singleton
tray_icon = TrayIcon()
