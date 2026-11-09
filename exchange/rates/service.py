"""Сведение курсов Rapira + (CryptoCards-логика через Bybit Сбер #20)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from exchange.config import Settings
from exchange.rates.bybit_p2p import fetch_nth_sber_ad_price
from exchange.rates.samples import RateSampleStore
from exchange.rates.sources import fetch_cryptocards_rate, fetch_rapira_usdt_rub

logger = logging.getLogger(__name__)

CC_PROXY_SOURCE = "bybit_sber20"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RateSnapshot:
    rapira: float | None
    cryptocards: float | None
    bybit_nth: float | None
    base: float
    client: float
    formula: str
    mode: str
    updated_at: datetime
    cc_samples_today: int = 0
    errors: tuple[str, ...] = ()

    def summary_html(self) -> str:
        rapira = f"{self.rapira:.4f}" if self.rapira is not None else "—"
        cc = f"{self.cryptocards:.4f}" if self.cryptocards is not None else "—"
        nth = f"{self.bybit_nth:.4f}" if self.bybit_nth is not None else "—"
        lines = [
            f"Режим: <b>{self.mode}</b> ({self.formula})",
            f"Rapira: <b>{rapira}</b> ₽/USDT",
            f"Bybit Сбер #20 (сейчас): <b>{nth}</b>",
            f"CryptoCards-логика (среднее за сутки): <b>{cc}</b>"
            + (f" · семплов: {self.cc_samples_today}" if self.cc_samples_today else ""),
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
    return max(values), "max"


class RateService:
    def __init__(self, settings: Settings, samples: RateSampleStore | None = None) -> None:
        self.settings = settings
        self.samples = samples
        self._lock = asyncio.Lock()
        base = settings.usdt_rate_rub
        client = settings.effective_rate()
        self._snapshot = RateSnapshot(
            rapira=None,
            cryptocards=None,
            bybit_nth=None,
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

    async def _fetch_cc_leg(self) -> tuple[float | None, float | None, int, str | None]:
        """
        Returns: (daily_avg_or_api_rate, current_nth_price, samples_count, error)
        """
        settings = self.settings
        source = settings.cc_rate_source

        if source == "api":
            if not (
                settings.cryptocards_api_url
                and (settings.cryptocards_authorization or settings.cryptocards_cookie)
            ):
                return None, None, 0, "CryptoCards API: нет Authorization/Cookie"
            try:
                rate = await fetch_cryptocards_rate(
                    api_url=settings.cryptocards_api_url,
                    authorization=settings.cryptocards_authorization,
                    cookie=settings.cryptocards_cookie,
                    rate_field=settings.cryptocards_rate_field,
                    timeout_sec=settings.rate_timeout_sec,
                )
                return rate, None, 0, None
            except Exception as exc:
                return None, None, 0, f"CryptoCards API: {exc}"

        # bybit_sber20 — логика саппорта CryptoCards без логина
        try:
            nth = await fetch_nth_sber_ad_price(
                ad_index=settings.bybit_ad_index,
                side=settings.bybit_side,
                payment_id=settings.bybit_payment_id,
                amount=settings.bybit_amount,
                timeout_sec=settings.rate_timeout_sec,
            )
        except Exception as exc:
            # Если свежий запрос упал — всё равно отдадим среднее за день, если есть
            err = f"Bybit Сбер#{settings.bybit_ad_index}: {exc}"
            if self.samples is None:
                return None, None, 0, err
            avg, count = await self.samples.day_average(CC_PROXY_SOURCE)
            return avg, None, count, err

        if self.samples is not None:
            await self.samples.add_sample(source=CC_PROXY_SOURCE, price=nth)
            avg, count = await self.samples.day_average(CC_PROXY_SOURCE)
            return avg if avg is not None else nth, nth, count, None
        return nth, nth, 0, None

    async def refresh(self) -> RateSnapshot:
        settings = self.settings
        if settings.rate_mode != "auto":
            snap = RateSnapshot(
                rapira=None,
                cryptocards=None,
                bybit_nth=None,
                base=settings.usdt_rate_rub,
                client=settings.effective_rate(),
                formula="static",
                mode="static",
                updated_at=utcnow(),
            )
            async with self._lock:
                self._snapshot = snap
            return snap

        rapira: float | None = None
        errors: list[str] = []

        try:
            rapira = await fetch_rapira_usdt_rub(timeout_sec=settings.rate_timeout_sec)
        except Exception as exc:
            logger.warning("Rapira rate failed: %s", exc)
            errors.append(f"Rapira: {exc}")

        cc_avg, nth, samples_count, cc_err = await self._fetch_cc_leg()
        if cc_err:
            logger.warning(cc_err)
            errors.append(cc_err)

        base, used_formula = combine_rates(
            rapira=rapira,
            cryptocards=cc_avg,
            formula=settings.rate_formula,
            fallback=settings.usdt_rate_rub,
        )
        client = base * (1.0 + settings.spread_percent / 100.0)
        snap = RateSnapshot(
            rapira=rapira,
            cryptocards=cc_avg,
            bybit_nth=nth,
            base=base,
            client=client,
            formula=used_formula,
            mode="auto",
            updated_at=utcnow(),
            cc_samples_today=samples_count,
            errors=tuple(errors),
        )
        async with self._lock:
            self._snapshot = snap
        logger.info(
            "Rates refreshed: rapira=%s cc_avg=%s nth=%s base=%.4f client=%.4f",
            rapira,
            cc_avg,
            nth,
            base,
            client,
        )
        return snap


def default_samples_path(database_path: Path) -> Path:
    return database_path.parent / "rate_samples.db"
