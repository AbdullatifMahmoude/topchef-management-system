import logging
import sys
from pythonjsonlogger import jsonlogger


def setup_logging():
    loghandler = logging.StreamHandler(sys.stdout)
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
    logger.setLevel(logging.INFO)

    return logger


logger = setup_logging()
