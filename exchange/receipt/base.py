from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ReceiptCheckResult:
    ok: bool
    provider: str
    message: str
    amount: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return "passed" if self.ok else "failed"


class ReceiptChecker(Protocol):
    async def check(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        mime_type: str | None,
        expected_amount: float,
        user_id: str,
        order_public_id: str,
    ) -> ReceiptCheckResult: ...
