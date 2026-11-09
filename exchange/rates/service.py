"""Сведение курсов Rapira + CryptoCards в клиентский курс."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from exchange.config import Settings
from exchange.rates.sources import fetch_cryptocards_rate, fetch_rapira_usdt_rub

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RateSnapshot:
    rapira: float | None
    cryptocards: float | None
    base: float
    client: float
    formula: str
    mode: str
    updated_at: datetime
    errors: tuple[str, ...] = ()

    def summary_html(self) -> str:
        rapira = f"{self.rapira:.4f}" if self.rapira is not None else "—"
        cc = f"{self.cryptocards:.4f}" if self.cryptocards is not None else "—"
        lines = [
            f"Режим: <b>{self.mode}</b> ({self.formula})",
            f"Rapira: <b>{rapira}</b> ₽/USDT",
            f"CryptoCards: <b>{cc}</b> ₽/USDT",
            f"База: <b>{self.base:.4f}</b>",
            f"Курс клиенту: <b>{self.client:.4f}</b> ₽/USDT",
            f"Обновлено: {self.updated_at.strftime('%H:%M:%S UTC')}",
        ]
        if self.errors:
            lines.append("Ошибки: " + "; ".join(self.errors))
        return "\n".join(lines)


def combine_rates(
    *,
    rapira: float | None,
    cryptocards: float | None,
    formula: str,
    fallback: float,
) -> tuple[float, str]:
    values = [v for v in (rapira, cryptocards) if v is not None and v > 0]
    if not values:
        return fallback, "fallback"
    formula = (formula or "max").lower()
    if formula == "min":
        return min(values), "min"
    if formula in {"avg", "mean", "average"}:
        return sum(values) / len(values), "avg"
    # max по умолчанию — консервативнее для обменника
    return max(values), "max"


class RateService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = asyncio.Lock()
        base = settings.usdt_rate_rub
        client = settings.effective_rate()
        self._snapshot = RateSnapshot(
            rapira=None,
            cryptocards=None,
            base=base,
            client=client,
            formula="static",
            mode="static",
            updated_at=utcnow(),
        )

    def client_rate(self) -> float:
        return self._snapshot.client

    def rub_to_usdt(self, amount_rub: float) -> float:
        return round(amount_rub / self.client_rate(), 6)

    def snapshot(self) -> RateSnapshot:
        return self._snapshot

    async def refresh(self) -> RateSnapshot:
        settings = self.settings
        if settings.rate_mode != "auto":
            base = settings.usdt_rate_rub
            snap = RateSnapshot(
                rapira=None,
                cryptocards=None,
                base=base,
                client=settings.effective_rate(),
                formula="static",
                mode="static",
                updated_at=utcnow(),
            )
            async with self._lock:
                self._snapshot = snap
            return snap

        rapira: float | None = None
        cryptocards: float | None = None
        errors: list[str] = []

        try:
            rapira = await fetch_rapira_usdt_rub(
                timeout_sec=settings.rate_timeout_sec
            )
        except Exception as exc:
            logger.warning("Rapira rate failed: %s", exc)
            errors.append(f"Rapira: {exc}")

        if settings.cryptocards_api_url and (
            settings.cryptocards_authorization or settings.cryptocards_cookie
        ):
            try:
                cryptocards = await fetch_cryptocards_rate(
                    api_url=settings.cryptocards_api_url,
                    authorization=settings.cryptocards_authorization,
                    cookie=settings.cryptocards_cookie,
                    rate_field=settings.cryptocards_rate_field,
                    timeout_sec=settings.rate_timeout_sec,
                )
            except Exception as exc:
                logger.warning("CryptoCards rate failed: %s", exc)
                errors.append(f"CryptoCards: {exc}")
        else:
            errors.append("CryptoCards: нет URL или Authorization/Cookie в .env")

        base, used_formula = combine_rates(
            rapira=rapira,
            cryptocards=cryptocards,
            formula=settings.rate_formula,
            fallback=settings.usdt_rate_rub,
        )
        client = base * (1.0 + settings.spread_percent / 100.0)
        snap = RateSnapshot(
            rapira=rapira,
            cryptocards=cryptocards,
            base=base,
            client=client,
            formula=used_formula,
            mode="auto",
            updated_at=utcnow(),
            errors=tuple(errors),
        )
        async with self._lock:
            self._snapshot = snap
        logger.info(
            "Rates refreshed: rapira=%s cc=%s base=%.4f client=%.4f",
            rapira,
            cryptocards,
            base,
            client,
        )
        return snap
