"""Mock-проверка чека для разработки без Fraudex API."""

from __future__ import annotations

import re

from exchange.receipt.base import ReceiptCheckResult


class MockReceiptChecker:
    """
    Правила:
    - имя файла / подпись содержит fail → rejected
    - иначе → passed, amount = expected_amount
    """

    provider = "mock"

    async def check(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        mime_type: str | None,
        expected_amount: float,
        user_id: str,
        order_public_id: str,
    ) -> ReceiptCheckResult:
        blob = f"{filename} {mime_type or ''}".lower()
        if "fail" in blob or b"FAIL_RECEIPT" in file_bytes[:2048]:
            return ReceiptCheckResult(
                ok=False,
                provider=self.provider,
                message="Mock: чек помечен как невалидный (fail в имени/содержимом)",
                amount=None,
                raw={"filename": filename, "bytes": len(file_bytes)},
            )

        # Если в тексте PDF/байтах есть сумма — попробуем вытащить (очень грубо).
        text_hint = file_bytes[:4096].decode("utf-8", errors="ignore")
        found = re.search(r"(\d+[.,]\d{2})", text_hint)
        amount = expected_amount
        if found:
            amount = float(found.group(1).replace(",", "."))

        return ReceiptCheckResult(
            ok=True,
            provider=self.provider,
            message="Mock: чек принят",
            amount=amount,
            raw={
                "filename": filename,
                "bytes": len(file_bytes),
                "user_id": user_id,
                "order": order_public_id,
            },
        )
