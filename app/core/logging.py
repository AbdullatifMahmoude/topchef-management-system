import logging
import sys
from pythonjsonlogger import jsonlogger


def setup_logging():
    loghandler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(timestamp)s %(level)s %(name)s %(message)s"
    )

    loghandler.setFormatter(formatter)

    logger = logging.getLogger()
    if not logger.handlers:
        logger.addHandler(loghandler)
    logger.setLevel(logging.INFO)

    return logger


logger = setup_logging()
