import logging
import os

LOG_LEVEL = os.environ.get("MCP_LOG_LEVEL", "INFO").upper()

LOG_FORMAT = (
    "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
)

def setup_logging():
    logging.basicConfig(
        level=LOG_LEVEL,
        format=LOG_FORMAT,
    )

def get_logger(name: str):
    return logging.getLogger(name)

