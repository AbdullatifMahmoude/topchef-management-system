import logging
import sys
from pythonjsonlogger import jsonlogger


def setup_logging():
    import os
    # In windowed mode (no console), sys.stdout is None
    stream = sys.stdout if sys.stdout is not None else sys.stderr
    if stream is None:
        loghandler = logging.NullHandler()
    else:
        loghandler = logging.StreamHandler(stream)
    
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
        json_ensure_ascii=False # Support Arabic in logs
    )
    loghandler.setFormatter(formatter)

    logger = logging.getLogger()
    if not logger.handlers:
        logger.addHandler(loghandler)
    
    # Desktop File Logging
    if os.environ.get("RUNTIME_MODE") == "desktop":
        try:
            from pathlib import Path
            # Try to find the logs directory relative to the EXE or script
            if getattr(sys, "frozen", False):
                base_dir = Path(sys.executable).parent
            else:
                # implementation/app/core/logging.py -> implementation/desktop/logs
                base_dir = Path(__file__).resolve().parent.parent.parent / "desktop"
            
            logs_dir = base_dir / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            log_file = logs_dir / "desktop.log"
            
            from logging.handlers import RotatingFileHandler
            fh = RotatingFileHandler(log_file, maxBytes=5_242_880, backupCount=5, encoding="utf-8")
            # Use a simpler formatter for the file if we want it human readable alongside JSON
            # Or just use the same JSON formatter. Let's use the JSON one for consistency.
            fh.setFormatter(formatter)
            logger.addHandler(fh)
        except Exception:
            pass

    logger.setLevel(logging.INFO)
    return logger


logger = setup_logging()
