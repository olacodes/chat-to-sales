import logging
import sys

from app.core.config import get_settings

_settings = get_settings()

LOG_LEVEL = logging.DEBUG if _settings.is_development else logging.INFO

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)

# Silence noisy third-party loggers in production
if _settings.is_production:
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Call at module level: logger = get_logger(__name__)"""
    return logging.getLogger(name)
