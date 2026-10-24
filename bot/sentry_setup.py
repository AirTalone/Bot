"""Optional Sentry wiring. No-op when SENTRY_DSN is empty or sdk missing."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def setup_sentry(dsn: str, *, environment: str = "production") -> bool:
    text = (dsn or "").strip()
    if not text:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return False
    sentry_sdk.init(
        dsn=text,
        environment=environment,
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    logger.info("sentry enabled env=%s", environment)
    return True
