"""Structured logging helpers."""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping

import structlog

from src.config.settings import Settings, get_settings

_configured = False


_SENSITIVE_QUERY_PARAM_RE = re.compile(r"([?&](?:key|token|access_token|api_key|apikey)=)([^&]+)", re.IGNORECASE)


def _scrub_sensitive(value: Any) -> Any:
    """Redact secrets in common logging shapes (urls, headers, nested dicts/lists)."""
    if value is None:
        return None
    if isinstance(value, str):
        return _SENSITIVE_QUERY_PARAM_RE.sub(r"\1[REDACTED]", value)
    if isinstance(value, list):
        return [_scrub_sensitive(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_scrub_sensitive(v) for v in value)
    if isinstance(value, dict):
        scrubbed: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if key.lower() in {"authorization", "x-api-key", "api-key"}:
                scrubbed[key] = "[REDACTED]"
            else:
                scrubbed[key] = _scrub_sensitive(v)
        return scrubbed
    return value


def _scrub_processor(_: Any, __: str, event_dict: Mapping[str, Any]) -> Mapping[str, Any]:
    """Structlog processor to scrub sensitive values from event dictionaries."""
    try:
        return _scrub_sensitive(dict(event_dict))  # type: ignore[return-value]
    except Exception:
        return event_dict


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

    # Reduce noisy third-party loggers that may leak URLs with query params.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.add_log_level,
            _scrub_processor,
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
