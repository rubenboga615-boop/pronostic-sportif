"""Configuration du logging avec loguru."""

import sys
from pathlib import Path

from loguru import logger

from app.config import settings


def setup_logging() -> None:
    """Configurer le logging de l'application."""
    logger.remove()

    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    logger.add(sys.stderr, format=log_format, level=settings.log_level)

    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.add(
        settings.log_file,
        format=log_format,
        level=settings.log_level,
        rotation="10 MB",
        retention="30 days",
        compression="gz",
    )
