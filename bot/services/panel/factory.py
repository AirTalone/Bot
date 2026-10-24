from __future__ import annotations

import json
from typing import Any

from bot.config import Settings
from bot.services.panel.base import PanelClient, PanelError
from bot.services.panel.marzban import MarzbanClient


def _parse_json_object(raw: str, *, field: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PanelError(f"{field} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise PanelError(f"{field} must be a JSON object")
    return value


def build_panel_client(settings: Settings) -> PanelClient | None:
    if not settings.panel_enabled:
        return None
    if settings.panel_provider != "marzban":
        raise PanelError(f"unsupported panel provider: {settings.panel_provider}")
    if not settings.panel_base_url or not settings.panel_username or not settings.panel_password:
        raise PanelError("PANEL_BASE_URL, PANEL_USERNAME and PANEL_PASSWORD are required when PANEL_ENABLED=true")
    proxies = _parse_json_object(settings.panel_proxies_json, field="PANEL_PROXIES_JSON") or {"vless": {}}
    inbounds_raw = _parse_json_object(settings.panel_inbounds_json, field="PANEL_INBOUNDS_JSON")
    inbounds: dict[str, list[str]] = {}
    for key, value in inbounds_raw.items():
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise PanelError("PANEL_INBOUNDS_JSON values must be arrays of strings")
        inbounds[str(key)] = list(value)
    return MarzbanClient(
        base_url=settings.panel_base_url,
        username=settings.panel_username,
        password=settings.panel_password,
        proxies=proxies,
        inbounds=inbounds,
    )
