"""Сведение курсов Rapira + CryptoCards и котировка под сумму заявки."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from exchange.config import Settings
from exchange.rates.bybit_p2p import fetch_nth_sber_ad_price
from exchange.rates.pricing import (
    RateQuote,
    combine_rates_legacy,
    compute_client_quote,
    effective_cc_cost,
    margin_percent,
    round_usdt_amount,
)
from exchange.rates.samples import RateSampleStore
from exchange.rates.sources import fetch_cryptocards_rate, fetch_rapira_usdt_rub

logger = logging.getLogger(__name__)

CC_PROXY_SOURCE = "bybit_sber20"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")


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
    effective_cost: float | None = None
    expected_margin_percent: float | None = None
    errors: tuple[str, ...] = ()

    def client_summary_html(
        self,
        *,
        min_amount_rub: float,
        max_amount_rub: float,
        discount_30k: float = 0.2,
        discount_40k: float = 0.3,
        tier_30k: float = 30_000.0,
        tier_40k: float = 40_000.0,
    ) -> str:
        """Короткий курс для клиента."""
        rate = f"{self.client:.2f}".rstrip("0").rstrip(".")
        updated_at = self.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        updated = updated_at.astimezone(MOSCOW_TZ).strftime("%H:%M")
        return (
            f"<b>{rate}</b> ₽ / USDT\n\n"
            f"от {min_amount_rub:,.0f} до {max_amount_rub:,.0f} ₽\n"
            f"от {tier_30k:,.0f} ₽ → −{discount_30k:g}\n"
            f"от {tier_40k:,.0f} ₽ → −{discount_40k:g}\n\n"
            f"обновлено {updated}"
        ).replace(",", " ")

    def summary_html(self) -> str:
        """Подробности для саппорта/админа."""
        rapira = f"{self.rapira:.2f}" if self.rapira is not None else "—"
        cc = f"{self.cryptocards:.2f}" if self.cryptocards is not None else "—"
        nth = f"{self.bybit_nth:.2f}" if self.bybit_nth is not None else "—"
        lines = [
            f"Режим: <b>{self.mode}</b> ({self.formula})",
            f"Rapira: <b>{rapira}</b> ₽ за 1 USDT",
            f"CryptoCards (закуп): <b>{cc}</b> ₽ за 1 USDT",
        ]
        if self.bybit_nth is not None or self.cc_samples_today:
            lines.append(f"Bybit Сбер #20 (сейчас): <b>{nth}</b>")
            if self.cc_samples_today:
                lines.append(f"Семплов CC-логики за сутки: {self.cc_samples_today}")
        if self.effective_cost is not None:
            lines.append(
                f"Себестоимость (курс, при котором ваш доход 0%): "
                f"<b>{self.effective_cost:.2f}</b>"
            )
        lines.append(f"Курс клиенту (база): <b>{self.client:.2f}</b>")
        if self.expected_margin_percent is not None:
            lines.append(
                f"Маржа к закупу: <b>{self.expected_margin_percent:.2f}%</b>"
            )
        lines.append(f"Обновлено: {self.updated_at.strftime('%H:%M:%S UTC')}")
        if self.errors:
            lines.append("Ошибки: " + "; ".join(self.errors))
        return "\n".join(lines)


# Обратная совместимость для тестов/импортов
def combine_rates(
    *,
    rapira: float | None,
    cryptocards: float | None,
    formula: str,
    fallback: float,
) -> tuple[float, str]:
    return combine_rates_legacy(
        rapira=rapira, cryptocards=cryptocards, formula=formula, fallback=fallback
    )


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
        """Базовый курс без скидки по сумме (для /rate и старых вызовов)."""
        return self._snapshot.client

    def rub_to_usdt(self, amount_rub: float) -> float:
        quote = self.quote_for_amount(amount_rub)
        return round_usdt_amount(amount_rub / quote.suggested_rate)

    def snapshot(self) -> RateSnapshot:
        return self._snapshot

    def quote_for_amount(self, amount_rub: float) -> RateQuote:
        snap = self._snapshot
        settings = self.settings
        if settings.rate_mode != "auto" or snap.mode == "static":
            # Статический режим: USDT_RATE_RUB (+ spread) с теми же скидками по сумме.
            base = settings.effective_rate()
            return compute_client_quote(
                amount_rub=amount_rub,
                rapira=base,
                cryptocards=None,
                fallback_rate=base,
                markup_rub=0.0,
                cc_edge_percent=settings.cc_edge_percent,
                tier_30k=settings.amount_tier_30k,
                tier_40k=settings.amount_tier_40k,
                discount_30k=settings.amount_discount_30k,
                discount_40k=settings.amount_discount_40k,
                min_margin_percent=settings.min_margin_percent,
                min_margin_percent_40k=settings.min_margin_percent_40k,
            )
        return compute_client_quote(
            amount_rub=amount_rub,
            rapira=snap.rapira,
            cryptocards=snap.cryptocards,
            fallback_rate=settings.usdt_rate_rub,
            markup_rub=settings.markup_rub_default,
            cc_edge_percent=settings.cc_edge_percent,
            tier_30k=settings.amount_tier_30k,
            tier_40k=settings.amount_tier_40k,
            discount_30k=settings.amount_discount_30k,
            discount_40k=settings.amount_discount_40k,
            min_margin_percent=settings.min_margin_percent,
            min_margin_percent_40k=settings.min_margin_percent_40k,
            formula=self._quote_formula(),
            income_percent=settings.target_income_percent,
        )

    def _quote_formula(self) -> str:
        """cc — курс от CC с вашим доходом; иначе — Rapira+markup."""
        return "cc" if (self.settings.rate_formula or "").lower() == "cc" else "spread"

    async def _fetch_cc_leg(self) -> tuple[float | None, float | None, int, str | None]:
        """
        Returns: (daily_avg_or_api_rate, current_nth_price, samples_count, error)
        """
        settings = self.settings
        source = settings.cc_rate_source

        if source == "api":
            if not settings.cryptocards_api_url:
                return None, None, 0, "CryptoCards API: нет CRYPTOCARDS_API_URL"
            if not (settings.cryptocards_token or settings.cryptocards_authorization):
                return (
                    None,
                    None,
                    0,
                    "CryptoCards API: нет CRYPTOCARDS_TOKEN (Local Storage → token)",
                )
            try:
                rate = await fetch_cryptocards_rate(
                    api_url=settings.cryptocards_api_url,
                    authorization=settings.cryptocards_authorization,
                    token=settings.cryptocards_token,
                    ukey=settings.cryptocards_ukey,
                    cookie=settings.cryptocards_cookie,
                    rate_field=settings.cryptocards_rate_field,
                    timeout_sec=settings.rate_timeout_sec,
                )
                return rate, None, 0, None
            except Exception as exc:
                return None, None, 0, f"CryptoCards API: {exc}"

        try:
            nth = await fetch_nth_sber_ad_price(
                ad_index=settings.bybit_ad_index,
                side=settings.bybit_side,
                payment_id=settings.bybit_payment_id,
                amount=settings.bybit_amount,
                timeout_sec=settings.rate_timeout_sec,
            )
        except Exception as exc:
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

        prev = self._snapshot
        rapira: float | None = None
        errors: list[str] = []

        try:
            rapira = await fetch_rapira_usdt_rub(timeout_sec=settings.rate_timeout_sec)
        except Exception as exc:
            logger.warning("Rapira rate failed: %s", exc)
            errors.append(f"Rapira: {exc}")
            # Не откатываемся на USDT_RATE_RUB=90 — держим последний удачный курс.
            if prev.mode == "auto" and prev.rapira is not None:
                rapira = prev.rapira
                errors.append("Rapira: использован предыдущий курс")

        cc_avg, nth, samples_count, cc_err = await self._fetch_cc_leg()
        if cc_err:
            logger.warning(cc_err)
            errors.append(cc_err)
            if cc_avg is None and prev.mode == "auto" and prev.cryptocards is not None:
                cc_avg = prev.cryptocards
                samples_count = prev.cc_samples_today
                errors.append("CryptoCards: использован предыдущий курс")

        formula_name = (settings.rate_formula or "cc").lower()
        if formula_name in {"cc", "spread", "profit", "margin"}:
            # Если свежих котировок нет, но в снимке уже был рабочий client — не прыгаем на 90.
            fallback = (
                prev.client
                if prev.mode == "auto" and prev.client > 0
                else settings.usdt_rate_rub
            )
            quote = compute_client_quote(
                amount_rub=0.0,
                rapira=rapira,
                cryptocards=cc_avg,
                fallback_rate=fallback,
                markup_rub=settings.markup_rub_default,
                cc_edge_percent=settings.cc_edge_percent,
                tier_30k=settings.amount_tier_30k,
                tier_40k=settings.amount_tier_40k,
                discount_30k=settings.amount_discount_30k,
                discount_40k=settings.amount_discount_40k,
                min_margin_percent=settings.min_margin_percent,
                min_margin_percent_40k=settings.min_margin_percent_40k,
                formula=self._quote_formula(),
                income_percent=settings.target_income_percent,
            )
            if quote.formula.startswith("cc") and quote.cryptocards is not None:
                base = quote.cryptocards
            else:
                base = quote.rapira if quote.rapira is not None else quote.suggested_rate
            client = quote.suggested_rate
            used_formula = quote.formula
            effective_cost = quote.effective_cost
            expected_margin = quote.margin_percent
        else:
            base, used_formula = combine_rates(
                rapira=rapira,
                cryptocards=cc_avg,
                formula=formula_name,
                fallback=settings.usdt_rate_rub,
            )
            client = base * (1.0 + settings.spread_percent / 100.0)
            effective_cost = None
            expected_margin = None
            if cc_avg is not None and cc_avg > 0:
                effective_cost = effective_cc_cost(cc_avg, settings.cc_edge_percent)
                expected_margin = margin_percent(client, effective_cost)

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
            effective_cost=effective_cost,
            expected_margin_percent=expected_margin,
            errors=tuple(errors),
        )
        async with self._lock:
            self._snapshot = snap
        logger.info(
            "Rates refreshed: rapira=%s cc_avg=%s nth=%s base=%.4f client=%.4f "
            "margin=%s formula=%s",
            rapira,
            cc_avg,
            nth,
            base,
            client,
            f"{expected_margin:.2f}%" if expected_margin is not None else "—",
            used_formula,
        )
        return snap


def default_samples_path(database_path: Path) -> Path:
    return database_path.parent / "rate_samples.db"
