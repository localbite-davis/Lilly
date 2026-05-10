"""Structlog configuration with PHI redaction."""

from __future__ import annotations

import logging
import sys

import structlog

PHI_FIELDS = {
    "phone", "first_name", "last_name", "ec_phone", "ec_name",
    "due_date", "baby_dob", "transcript", "summary", "body",
}


def _redact_phi(logger: object, method: str, event_dict: dict) -> dict:
    from src.config import settings
    if not settings.phi_redaction:
        return event_dict
    for k in list(event_dict.keys()):
        if k.lower() in PHI_FIELDS:
            event_dict[k] = "<redacted>"
    return event_dict


def configure_logging() -> None:
    from src.config import settings

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            _redact_phi,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )


configure_logging()
