"""
Desktop Logging System
──────────────────────
Rotating file + console logger with UTF‑8 support for Arabic output.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

from desktop.config import config, LOGS_DIR


def setup_logger(name: str = "topchef_desktop") -> logging.Logger:
    """Create and configure the application‑wide logger."""
    logger = logging.getLogger(name)
    level = getattr(logging, config.get("log_level", "INFO").upper(), logging.INFO)
    logger.setLevel(level)

    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-8s %(name)s – %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── Console handler ──
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # ── Rotating file handler ──
    log_file = LOGS_DIR / "desktop.log"
    fh = RotatingFileHandler(
        log_file,
        maxBytes=config.get("log_max_bytes", 5_242_880),
        backupCount=config.get("log_backup_count", 5),
        encoding="utf-8",
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# Module‑level logger instance
desktop_logger = setup_logger()
