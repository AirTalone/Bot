"""
HTTP-адаптер под Fraudex / аналогичные сервисы проверки PDF-чеков.

Публичного стабильного API у Fraudex в открытом доступе нет, поэтому контракт
настраивается через env:

  RECEIPT_API_URL   — endpoint (POST multipart)
  RECEIPT_API_KEY   — ключ (Authorization: Bearer … и поле api_key)

Ожидаемый ответ JSON (достаточно одного из признаков успеха):
  {"ok": true, "message": "...", "amount": 1000.0}
  {"success": true, ...}
  {"valid": true, ...}
  {"status": "ok"|"passed"|"valid"|"success", ...}
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from exchange.receipt.base import ReceiptCheckResult

logger = logging.getLogger(__name__)


def _as_bool_success(payload: dict[str, Any]) -> bool | None:
    for key in ("ok", "success", "valid", "is_valid", "passed"):
        if key in payload and isinstance(payload[key], bool):
            return payload[key]
    status = str(payload.get("status", "")).lower()
    if status in {"ok", "passed", "valid", "success", "approved"}:
        return True
    if status in {"fail", "failed", "invalid", "rejected", "error"}:
        return False
    message = str(payload.get("message", "")).lower()
    if "валиден" in message or "valid" in message or "успеш" in message:
        return True
    if "невалид" in message or "invalid" in message or "поддел" in message:
        return False
    return None


class HttpReceiptChecker:
    provider = "http"

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        timeout_sec: float = 30.0,
    ) -> None:
        if not api_url:
            raise ValueError("RECEIPT_API_URL is required for http receipt provider")
        self.api_url = api_url
        self.api_key = api_key
        self.timeout_sec = timeout_sec

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
        form = aiohttp.FormData()
        form.add_field("api_key", self.api_key)
        form.add_field("user_id", user_id)
        form.add_field("order_id", order_public_id)
        form.add_field("price", str(expected_amount))
        form.add_field("expected_amount", str(expected_amount))
        form.add_field(
            "file",
            file_bytes,
            filename=filename or "receipt.pdf",
            content_type=mime_type or "application/octet-stream",
        )

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        timeout = aiohttp.ClientTimeout(total=self.timeout_sec)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    self.api_url, data=form, headers=headers
                ) as resp:
                    raw_text = await resp.text()
                    try:
                        payload: dict[str, Any] = await resp.json(content_type=None)
                    except Exception:
                        payload = {"raw_text": raw_text, "http_status": resp.status}

                    if resp.status >= 400:
                        return ReceiptCheckResult(
                            ok=False,
                            provider=self.provider,
                            message=f"HTTP {resp.status}: {payload.get('message') or raw_text[:200]}",
                            raw=payload if isinstance(payload, dict) else {"raw": payload},
                        )

                    ok = _as_bool_success(payload if isinstance(payload, dict) else {})
                    if ok is None:
                        ok = resp.status == 200

                    amount = None
                    if isinstance(payload, dict):
                        for key in ("amount", "sum", "total", "price"):
                            if key in payload:
                                try:
                                    amount = float(payload[key])
                                    break
                                except (TypeError, ValueError):
                                    pass

                    message = ""
                    if isinstance(payload, dict):
                        message = str(
                            payload.get("message")
                            or payload.get("detail")
                            or payload.get("status")
                            or ("чек валиден" if ok else "чек отклонён")
                        )

                    return ReceiptCheckResult(
                        ok=bool(ok),
                        provider=self.provider,
                        message=message,
                        amount=amount,
                        raw=payload if isinstance(payload, dict) else {"raw": payload},
                    )
        except Exception as exc:
            logger.exception("Receipt HTTP check failed")
            return ReceiptCheckResult(
                ok=False,
                provider=self.provider,
                message=f"Ошибка запроса к сервису проверки: {exc}",
                raw={"error": str(exc)},
            )
