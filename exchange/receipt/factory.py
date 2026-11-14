from __future__ import annotations

from exchange.config import Settings
from exchange.receipt.base import ReceiptChecker
from exchange.receipt.http_provider import HttpReceiptChecker
from exchange.receipt.mock import MockReceiptChecker


def build_receipt_checker(settings: Settings) -> ReceiptChecker:
    provider = settings.receipt_provider
    if provider in {"mock", "dev", "test"}:
        return MockReceiptChecker()
    if provider in {"http", "fraudex", "api"}:
        return HttpReceiptChecker(
            api_url=settings.receipt_api_url,
            api_key=settings.receipt_api_key,
            timeout_sec=settings.receipt_api_timeout_sec,
        )
    raise ValueError(f"Unknown RECEIPT_PROVIDER: {provider}")
