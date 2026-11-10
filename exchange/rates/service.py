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
    effective_cost: float | None = None
    expected_margin_percent: float | None = None
    errors: tuple[str, ...] = ()

    def summary_html(self) -> str:
        rapira = f"{self.rapira:.4f}" if self.rapira is not None else "—"
        cc = f"{self.cryptocards:.4f}" if self.cryptocards is not None else "—"
        nth = f"{self.bybit_nth:.4f}" if self.bybit_nth is not None else "—"
        lines = [
            f"Режим: <b>{self.mode}</b> ({self.formula})",
            f"Rapira: <b>{rapira}</b> ₽/USDT",
            f"CryptoCards: <b>{cc}</b> ₽/USDT",
        ]
        if self.bybit_nth is not None or self.cc_samples_today:
            lines.append(f"Bybit Сбер #20 (сейчас): <b>{nth}</b>")
            if self.cc_samples_today:
                lines.append(f"Семплов CC-логики за сутки: {self.cc_samples_today}")
        if self.effective_cost is not None:
            lines.append(f"Себестоимость (CC − edge): <b>{self.effective_cost:.4f}</b>")
        lines.extend(
            [
                f"База: <b>{self.base:.4f}</b>",
                f"Курс клиенту: <b>{self.client:.4f}</b> ₽/USDT",
            ]
        )
        if self.expected_margin_percent is not None:
            lines.append(f"Ожидаемая маржа: <b>{self.expected_margin_percent:.2f}%</b>")
        lines.append(f"Обновлено: {self.updated_at.strftime('%H:%M:%S UTC')}")
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


def effective_cc_cost(cryptocards: float, cc_edge_percent: float) -> float:
    """Себестоимость 1 USDT с учётом твоего спреда на CryptoCards."""
    edge = max(0.0, cc_edge_percent) / 100.0
    return cryptocards * (1.0 - edge)


def margin_percent(client_rate: float, cost: float) -> float:
    if cost <= 0:
        return 0.0
    return (client_rate / cost - 1.0) * 100.0


def compute_spread_rate(
    *,
    rapira: float | None,
    cryptocards: float | None,
    fallback: float,
    cc_edge_percent: float = 2.0,
    target_margin_percent: float = 1.5,
    good_gap_percent: float = 0.3,
    markup_rub_default: float = 1.0,
    markup_rub_good: float = 0.7,
) -> tuple[float, float, float | None, float | None, str]:
    """
    Курс клиенту под целевую маржу 1–2% с учётом спреда CryptoCards (~2%).

    Логика:
    - себестоимость = CC × (1 − cc_edge/100)
    - если Rapira выше CC на good_gap% и больше → «хороший» рынок:
      клиенту Rapira + markup_good (обычно +0.7 ₽) → суммарно ~3%
    - если курсы близки / Rapira не выше → целимся в target_margin от себестоимости
      (в среднем 1–2%), с потолком Rapira + markup_default

    Returns: (base, client, effective_cost, expected_margin_pct, formula_label)
    """
    cc = cryptocards if cryptocards is not None and cryptocards > 0 else None
    rp = rapira if rapira is not None and rapira > 0 else None

    if cc is None and rp is None:
        return fallback, fallback, None, None, "fallback"

    if cc is None:
        # Только Rapira: прежняя привычка Rapira + 1 ₽
        base = rp  # type: ignore[assignment]
        client = rp + markup_rub_default
        return base, client, None, None, f"spread:rapira+{markup_rub_default:g}"

    cost = effective_cc_cost(cc, cc_edge_percent)
    target_client = cost * (1.0 + max(0.0, target_margin_percent) / 100.0)

    if rp is None:
        return cc, target_client, cost, margin_percent(target_client, cost), (
            f"spread:target{target_margin_percent:g}%"
        )

    gap_pct = (rp - cc) / cc * 100.0
    if gap_pct >= good_gap_percent:
        # Rapira чуть выше CC → Rapira + 0.7, плюс ~2% с CC ≈ ~3%
        base = rp
        client = rp + markup_rub_good
        label = f"spread:rapira+{markup_rub_good:g} (good)"
    else:
        # Курсы сошлись / Rapira не выше: целимся в 1–2% от себестоимости (CC − edge).
        # Потолок — привычный Rapira + 1 ₽, чтобы не задирать курс выше обычного.
        base = rp
        ceiling = rp + markup_rub_default
        client = min(target_client, ceiling)
        label = f"spread:target{target_margin_percent:g}%"

    return base, client, cost, margin_percent(client, cost), label


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

        effective_cost: float | None = None
        expected_margin: float | None = None
        formula_name = (settings.rate_formula or "spread").lower()

        if formula_name in {"spread", "profit", "margin"}:
            base, client, effective_cost, expected_margin, used_formula = (
                compute_spread_rate(
                    rapira=rapira,
                    cryptocards=cc_avg,
                    fallback=settings.usdt_rate_rub,
                    cc_edge_percent=settings.cc_edge_percent,
                    target_margin_percent=settings.target_margin_percent,
                    good_gap_percent=settings.good_gap_percent,
                    markup_rub_default=settings.markup_rub_default,
                    markup_rub_good=settings.markup_rub_good,
                )
            )
        else:
            base, used_formula = combine_rates(
                rapira=rapira,
                cryptocards=cc_avg,
                formula=formula_name,
                fallback=settings.usdt_rate_rub,
            )
            client = base * (1.0 + settings.spread_percent / 100.0)
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
