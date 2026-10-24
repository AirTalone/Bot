import json
import logging
from pathlib import Path

from bot.logging_setup import JsonFormatter
from bot.sentry_setup import setup_sentry
from bot.services.heartbeat import heartbeat_age_seconds, touch_heartbeat


def test_touch_heartbeat(tmp_path: Path) -> None:
    path = tmp_path / "hb"
    touch_heartbeat(str(path))
    assert path.exists()
    age = heartbeat_age_seconds(str(path))
    assert age is not None
    assert age < 5


def test_json_formatter_roundtrip() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    line = JsonFormatter().format(record)
    data = json.loads(line)
    assert data["msg"] == "hello world"
    assert data["level"] == "INFO"


def test_sentry_noop_without_dsn() -> None:
    assert setup_sentry("") is False
