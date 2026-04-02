import logging
import sys

# Configure root logger
logger = logging.getLogger("clericus")
logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("[%(asctime)s] %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
handler.setFormatter(formatter)
logger.addHandler(handler)


def log_info(message: str):
    logger.info(message)


def log_error(message: str, exc: Exception = None):
    if exc:
        logger.error(f"{message}: {exc}")
    else:
        logger.error(message)
