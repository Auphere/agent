"""Structured logging helpers."""

from __future__ import annotations

import logging

import structlog

from src.config.settings import Settings, get_settings

_configured = False


def _configure_logging(level: str) -> None:
    """Configure structlog and stdlib logging only once."""
    global _configured
    
    if _configured:
        return
        
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[logging.StreamHandler()],
    )

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    
    _configured = True


def get_logger(name: str = "auphere-agent", settings: Settings | None = None) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger."""

    settings = settings or get_settings()
    _configure_logging(settings.log_level.upper())
    return structlog.get_logger(name).bind(environment=settings.environment)
