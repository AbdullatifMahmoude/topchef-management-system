import logging
import sys
from pythonjsonlogger import json


def setup_logging():
    # In windowed mode (no console), sys.stdout is None
    stream = sys.stdout if sys.stdout is not None else sys.stderr
    if stream is None:
        loghandler = logging.NullHandler()
    else:
        loghandler = logging.StreamHandler(stream)
    
    formatter = json.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        rename_fields={"asctime": "timestamp", "levelname": "level"},
        json_ensure_ascii=False # Support Arabic in logs
    )
    loghandler.setFormatter(formatter)

    logger = logging.getLogger()
    if not logger.handlers:
        logger.addHandler(loghandler)
    
    try:
        from pathlib import Path
        log_file = Path("logs/api.log")
        log_file.parent.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler
        fh = RotatingFileHandler(log_file, maxBytes=5_242_880, backupCount=5, encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        pass

    logger.setLevel(logging.INFO)
    return logger


logger = setup_logging()
