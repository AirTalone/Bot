from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class PanelError(Exception):
    """Raised when the VPN panel rejects or fails a request."""


@dataclass(frozen=True, slots=True)
class ProvisionedAccess:
    username: str
    subscription_url: str
    expires_at: datetime | None
    created: bool


class PanelClient(Protocol):
    async def ensure_subscription(
        self,
        *,
        username: str,
        duration_days: int,
        note: str = "",
    ) -> ProvisionedAccess: ...

    async def aclose(self) -> None: ...
