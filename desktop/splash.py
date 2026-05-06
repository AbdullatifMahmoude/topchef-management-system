"""
Splash Screen
─────────────
Displays a professional loading screen while the local FastAPI server boots.
Uses tkinter (bundled with Python) – zero extra dependencies.
"""

import threading
import tkinter as tk
import os
from typing import Optional

from desktop.config import config, ASSETS_DIR
from desktop.logger import desktop_logger as log


class SplashScreen:
    """Non‑blocking splash that auto‑closes when told to."""

    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._thread: Optional[threading.Thread] = None
        self._closed = threading.Event()
        self._logo_img = None

    def show(self):
        """Show the splash in a background thread."""
        self._closed.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="splash")
        self._thread.start()

    def close(self):
        """Signal the splash to close gracefully."""
        self._closed.set()
        if self._root:
            try:
                # Use quit() instead of destroy() for a cleaner exit from mainloop
                self._root.after(0, self._root.quit)
            except Exception:
                pass

    def _run(self):
        try:
            log.info("Splash: Initialising Tkinter...")
            self._root = tk.Tk()
            self._root.overrideredirect(True)  # No title bar

            # ── Dimensions ──
            w, h = 500, 350
            sw = self._root.winfo_screenwidth()
            sh = self._root.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2
            self._root.geometry(f"{w}x{h}+{x}+{y}")
            
            # --- Frontend Colors ---
            color_bg = "#0f0f0f"
            color_primary = "#c9a84c"
            color_text = "#f0e6cc"
            color_subtext = "#8a7a5a"
            
            self._root.configure(bg=color_bg)
            self._root.attributes("-topmost", True)

            log.info("Splash: Creating canvas...")
            canvas = tk.Canvas(self._root, width=w, height=h, highlightthickness=0, bg=color_bg)
            canvas.pack(fill="both", expand=True)

            # Decorative accent borders (Gold)
            canvas.create_rectangle(0, 0, w, 4, fill=color_primary, outline="")
            canvas.create_rectangle(0, h-4, w, h, fill=color_primary, outline="")

            # --- Logo Handling ---
            logo_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app", "frontend", "assets", "توب شيف 1.png"))
            if os.path.exists(logo_path):
                try:
                    from PIL import Image, ImageTk
                    pil_img = Image.open(logo_path)
                    pil_img = pil_img.resize((120, 120), Image.Resampling.LANCZOS)
                    self._logo_img = ImageTk.PhotoImage(pil_img)
                    canvas.create_image(w // 2, h // 2 - 60, image=self._logo_img)
                    log.info("Splash: Logo loaded successfully.")
                except Exception as e:
                    log.debug(f"Splash: Could not load logo image: {e}")
                    canvas.create_text(w // 2, h // 2 - 60, text="🍽️", fill=color_primary, font=("Segoe UI", 48))
            else:
                log.warning(f"Splash: Logo not found at {logo_path}")
                canvas.create_text(w // 2, h // 2 - 60, text="🍽️", fill=color_primary, font=("Segoe UI", 48))

            # Title (Arabic)
            canvas.create_text(
                w // 2, h // 2 + 35,
                text="مطعم توب شيف للمشويات",
                fill=color_primary,
                font=("Cairo", 22, "bold"),
            )

            # Subtitle
            canvas.create_text(
                w // 2, h // 2 + 75,
                text="نظام إدارة نقاط البيع الذكي",
                fill=color_text,
                font=("Cairo", 12),
            )

            # Version
            ver = config.get_local_version()
            canvas.create_text(
                w // 2, h // 2 + 105,
                text=f"إصدار المؤسسات v{ver}",
                fill=color_subtext,
                font=("Segoe UI", 9),
            )

            # Loading indicator
            self._loading_text_id = canvas.create_text(
                w // 2, h - 50,
                text="جاري بدء النظام...",
                fill=color_primary,
                font=("Cairo", 11, "bold"),
            )

            # Animated dots
            self._dot_count = 0
            self._canvas = canvas
            self._animate()

            # Auto‑close polling
            self._poll_close()

            log.info("Splash: Entering mainloop.")
            self._root.mainloop()
        except Exception as exc:
            log.error("Splash screen error: %s", exc)

    def _animate(self):
        if self._closed.is_set():
            return
        self._dot_count = (self._dot_count + 1) % 4
        dots = "." * self._dot_count
        if self._canvas:
            self._canvas.itemconfig(
                self._loading_text_id,
                text=f"جاري بدء النظام{dots}",
            )
        if self._root:
            self._root.after(400, self._animate)

    def _poll_close(self):
        if self._closed.is_set():
            try:
                self._root.destroy()
            except Exception:
                pass
            return
        if self._root:
            self._root.after(100, self._poll_close)


# Module‑level singleton
splash = SplashScreen()
