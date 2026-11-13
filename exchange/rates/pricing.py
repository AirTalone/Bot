"""Расчёт клиентского курса по опросу: Rapira+1, скидки по сумме, маржа к CC."""

from __future__ import annotations

from dataclasses import dataclass


def combine_rates_legacy(
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


def round_usdt_amount(value: float) -> float:
    """
    Сумма USDT к выплате клиенту.
    Обычно до десятых (229.2789 → 229.3). Если при округлении до десятых
    клиент теряет больше 0.02 USDT — до сотых (229.2449 → 229.24).
    """
    tenths = round(float(value), 1)
    if value - tenths > 0.02:
        return round(float(value), 2)
    return tenths


def effective_cc_cost(cryptocards: float, cc_edge_percent: float) -> float:
    """Себестоимость 1 USDT: курс CC минус макс. чистый доход с площадки."""
    edge = max(0.0, float(cc_edge_percent)) / 100.0
    return float(cryptocards) * (1.0 - edge)


def margin_percent(client_rate: float, cost: float) -> float:
    if cost <= 0:
        return 0.0
    return (float(client_rate) / float(cost) - 1.0) * 100.0


def amount_discount_rub(
    amount_rub: float,
    *,
    tier_30k: float = 30_000.0,
    tier_40k: float = 40_000.0,
    discount_30k: float = 0.2,
    discount_40k: float = 0.3,
) -> float:
    """Скидка с курса клиенту по сумме заявки (₽ к курсу)."""
    if amount_rub > tier_40k:
        return float(discount_40k)
    if amount_rub > tier_30k:
        return float(discount_30k)
    return 0.0


def min_margin_for_amount(
    amount_rub: float,
    *,
    tier_40k: float = 40_000.0,
    min_margin_percent: float = 1.0,
    min_margin_percent_40k: float = 0.5,
) -> float:
    if amount_rub > tier_40k:
        return float(min_margin_percent_40k)
    return float(min_margin_percent)


@dataclass(frozen=True)
class RateQuote:
    """Снимок котировки под сумму заявки."""

    rapira: float | None
    cryptocards: float | None
    amount_rub: float
    markup_rub: float
    amount_discount_rub: float
    suggested_rate: float
    effective_cost: float | None
    margin_percent: float | None
    min_margin_percent: float
    margin_ok: bool | None
    formula: str

    def to_extra(self) -> dict:
        return {
            "rapira": self.rapira,
            "cryptocards": self.cryptocards,
            "markup_rub": self.markup_rub,
            "amount_discount_rub": self.amount_discount_rub,
            "suggested_rate": self.suggested_rate,
            "effective_cost": self.effective_cost,
            "margin_percent": self.margin_percent,
            "min_margin_percent": self.min_margin_percent,
            "margin_ok": self.margin_ok,
            "quote_formula": self.formula,
        }

    def support_block_html(self, *, final_rate: float | None = None) -> str:
        rapira = f"{self.rapira:.2f}" if self.rapira is not None else "—"
        cc = f"{self.cryptocards:.2f}" if self.cryptocards is not None else "—"
        cost = (
            f"{self.effective_cost:.2f}" if self.effective_cost is not None else "—"
        )
        rate = final_rate if final_rate is not None else self.suggested_rate
        margin = self.margin_percent
        if (
            final_rate is not None
            and self.effective_cost is not None
            and self.effective_cost > 0
        ):
            margin = margin_percent(final_rate, self.effective_cost)
        margin_s = f"{margin:.2f}%" if margin is not None else "—"
        if self.margin_ok is True:
            verdict = "✅ маржа ок"
        elif self.margin_ok is False:
            verdict = "⚠️ ниже минимума — решение саппорта"
        else:
            verdict = "❓ нет CC — проверь вручную"
        lines = [
            f"Rapira: <b>{rapira}</b>",
            f"CryptoCards (закуп): <b>{cc}</b>",
            f"Себестоимость (CC − edge): <b>{cost}</b>",
            f"Предложенный курс: <b>{self.suggested_rate:.2f}</b> ({self.formula})",
            f"Итоговый курс: <b>{rate:.2f}</b>",
            f"Маржа: <b>{margin_s}</b> (мин. {self.min_margin_percent:.2f}%) — {verdict}",
        ]
        if self.amount_discount_rub > 0:
            lines.insert(
                3,
                f"Скидка по сумме: <b>−{self.amount_discount_rub:g}</b> ₽ к курсу",
            )
        return "\n".join(lines)


def compute_client_quote(
    *,
    amount_rub: float,
    rapira: float | None,
    cryptocards: float | None,
    fallback_rate: float,
    markup_rub: float = 1.0,
    cc_edge_percent: float = 2.0,
    tier_30k: float = 30_000.0,
    tier_40k: float = 40_000.0,
    discount_30k: float = 0.2,
    discount_40k: float = 0.3,
    min_margin_percent: float = 1.0,
    min_margin_percent_40k: float = 0.5,
) -> RateQuote:
    """
    Клиенту база всегда Rapira.
    Черновик курса: Rapira + markup (− скидка по сумме >30к / >40к).
    CC — только закуп и проверка маржи (макс. чистый доход с CC = cc_edge).
    """
    discount = amount_discount_rub(
        amount_rub,
        tier_30k=tier_30k,
        tier_40k=tier_40k,
        discount_30k=discount_30k,
        discount_40k=discount_40k,
    )
    min_m = min_margin_for_amount(
        amount_rub,
        tier_40k=tier_40k,
        min_margin_percent=min_margin_percent,
        min_margin_percent_40k=min_margin_percent_40k,
    )

    rp = rapira if rapira is not None and rapira > 0 else None
    cc = cryptocards if cryptocards is not None and cryptocards > 0 else None

    if rp is not None:
        suggested = rp + float(markup_rub) - discount
        formula = f"rapira+{markup_rub:g}"
        if discount > 0:
            formula += f"-{discount:g}"
    else:
        suggested = float(fallback_rate)
        formula = "fallback"

    if suggested <= 0:
        suggested = float(fallback_rate)
        formula = "fallback"

    # Курс клиенту — до сотых: показанный курс = курс, по которому считаются USDT
    suggested = round(suggested, 2)

    cost = effective_cc_cost(cc, cc_edge_percent) if cc is not None else None
    margin = margin_percent(suggested, cost) if cost is not None else None
    margin_ok: bool | None
    if margin is None:
        margin_ok = None
    else:
        margin_ok = margin >= min_m

    return RateQuote(
        rapira=rp,
        cryptocards=cc,
        amount_rub=float(amount_rub),
        markup_rub=float(markup_rub),
        amount_discount_rub=discount,
        suggested_rate=suggested,
        effective_cost=round(cost, 4) if cost is not None else None,
        margin_percent=round(margin, 4) if margin is not None else None,
        min_margin_percent=min_m,
        margin_ok=margin_ok,
        formula=formula,
    )


def reevaluate_margin(
    *,
    client_rate: float,
    cryptocards: float | None,
    amount_rub: float,
    cc_edge_percent: float = 2.0,
    tier_40k: float = 40_000.0,
    min_margin_percent: float = 1.0,
    min_margin_percent_40k: float = 0.5,
) -> tuple[float | None, float | None, float, bool | None]:
    """Пересчёт маржи после ручной правки курса саппортом."""
    min_m = min_margin_for_amount(
        amount_rub,
        tier_40k=tier_40k,
        min_margin_percent=min_margin_percent,
        min_margin_percent_40k=min_margin_percent_40k,
    )
    if cryptocards is None or cryptocards <= 0:
        return None, None, min_m, None
    cost = effective_cc_cost(cryptocards, cc_edge_percent)
    margin = margin_percent(client_rate, cost)
    return cost, margin, min_m, margin >= min_m
