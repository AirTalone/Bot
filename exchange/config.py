"""Конфигурация из переменных окружения."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _parse_id_set(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        ids.add(int(part))
    return frozenset(ids)


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: Path
    admin_ids: frozenset[int]
    support_ids: frozenset[int]
    usdt_rate_rub: float
    spread_percent: float
    min_amount_rub: float
    max_amount_rub: float
    payment_ttl_minutes: int
    receipt_provider: str  # mock | http
    receipt_api_url: str
    receipt_api_key: str
    receipt_api_timeout_sec: float
    # Если true — при провале HTTP-провайдера заявка всё равно уходит саппорту
    # со статусом «чек отклонён», а не зависает.
    receipt_fail_open_to_support: bool
    # Курсы
    rate_mode: str  # static | auto
    rate_formula: str  # max | min | avg
    rate_refresh_sec: int
    rate_timeout_sec: float
    cryptocards_api_url: str
    cryptocards_authorization: str
    cryptocards_cookie: str
    cryptocards_rate_field: str

    def is_admin(self, tg_id: int) -> bool:
        return tg_id in self.admin_ids

    def is_support(self, tg_id: int) -> bool:
        return tg_id in self.support_ids or self.is_admin(tg_id)

    def effective_rate(self) -> float:
        """Статический курс USDT с учётом спреда (fallback)."""
        if self.usdt_rate_rub <= 0:
            raise ValueError("USDT_RATE_RUB must be > 0")
        return self.usdt_rate_rub * (1.0 + self.spread_percent / 100.0)

    def rub_to_usdt(self, amount_rub: float) -> float:
        return round(amount_rub / self.effective_rate(), 6)


def load_settings() -> Settings:
    db = os.getenv("DATABASE_PATH", "data/exchange.db").strip()
    auth = os.getenv("CRYPTOCARDS_AUTHORIZATION", "").strip()
    token = os.getenv("CRYPTOCARDS_TOKEN", "").strip()
    if not auth and token:
        # Удобный короткий вариант: только токен → Bearer
        auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        database_path=Path(db),
        admin_ids=_parse_id_set(os.getenv("ADMIN_IDS", "")),
        support_ids=_parse_id_set(os.getenv("SUPPORT_IDS", "")),
        usdt_rate_rub=float(os.getenv("USDT_RATE_RUB", "90")),
        spread_percent=float(os.getenv("SPREAD_PERCENT", "2")),
        min_amount_rub=float(os.getenv("MIN_AMOUNT_RUB", "1000")),
        max_amount_rub=float(os.getenv("MAX_AMOUNT_RUB", "500000")),
        payment_ttl_minutes=int(os.getenv("PAYMENT_TTL_MINUTES", "20")),
        receipt_provider=os.getenv("RECEIPT_PROVIDER", "mock").strip().lower(),
        receipt_api_url=os.getenv("RECEIPT_API_URL", "").strip(),
        receipt_api_key=os.getenv("RECEIPT_API_KEY", "").strip(),
        receipt_api_timeout_sec=float(os.getenv("RECEIPT_API_TIMEOUT_SEC", "30")),
        receipt_fail_open_to_support=os.getenv(
            "RECEIPT_FAIL_OPEN_TO_SUPPORT", "true"
        )
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
        rate_mode=os.getenv("RATE_MODE", "auto").strip().lower(),
        rate_formula=os.getenv("RATE_FORMULA", "max").strip().lower(),
        rate_refresh_sec=int(os.getenv("RATE_REFRESH_SEC", "60")),
        rate_timeout_sec=float(os.getenv("RATE_TIMEOUT_SEC", "15")),
        cryptocards_api_url=os.getenv(
            "CRYPTOCARDS_API_URL", "https://cryptocards.ws/api/account"
        ).strip(),
        cryptocards_authorization=auth,
        cryptocards_cookie=os.getenv("CRYPTOCARDS_COOKIE", "").strip(),
        cryptocards_rate_field=os.getenv("CRYPTOCARDS_RATE_FIELD", "rate").strip()
        or "rate",
    )
