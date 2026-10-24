"""In-memory antispam cooldowns keyed by telegram user id."""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CooldownHit:
    retry_after_seconds: int


class CooldownGate:
    def __init__(self) -> None:
        self._last: dict[tuple[str, int], float] = {}

    def check(self, key: str, user_id: int, cooldown_seconds: int) -> CooldownHit | None:
        if cooldown_seconds <= 0:
            return None
        now = time.monotonic()
        stamp = self._last.get((key, user_id))
        if stamp is None:
            return None
        elapsed = now - stamp
        if elapsed >= cooldown_seconds:
            return None
        return CooldownHit(retry_after_seconds=max(1, int(cooldown_seconds - elapsed) + 1))

    def hit(self, key: str, user_id: int) -> None:
        self._last[(key, user_id)] = time.monotonic()

    def clear(self, key: str, user_id: int) -> None:
        self._last.pop((key, user_id), None)


ORDER_CREATE = "order_create"
CLAIM_PAID = "claim_paid"

gate = CooldownGate()
