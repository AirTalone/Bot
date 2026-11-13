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


def _parse_optional_int(raw: str) -> int | None:
    raw = (raw or "").strip()
    return int(raw) if raw else None


@dataclass(frozen=True)
class Settings:
    bot_token: str
    database_path: Path
    admin_ids: frozenset[int]
    support_ids: frozenset[int]
    # Рабочая группа сотрудников: туда приходят карточки заявок. None — по-старому, в личку.
    staff_chat_id: int | None
    # Юзернейм оператора поддержки для клиентов (без @)
    support_contact: str
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
    rate_formula: str  # cc (от курса CC) | spread (Rapira+1) | max | min | avg
    # Формула cc: ваш доход с заявки, % (из максимальных CC_EDGE_PERCENT = 2%)
    target_income_percent: float
    rate_refresh_sec: int
    rate_timeout_sec: float
    cryptocards_api_url: str
    cryptocards_authorization: str
    cryptocards_token: str  # Local Storage "token" → заголовок x-token
    cryptocards_ukey: str  # Local Storage "ukey" → заголовок x-ukey
    cryptocards_cookie: str
    cryptocards_rate_field: str
    # Формула spread: клиенту Rapira+markup, CC = закуп (макс. чистый доход = edge)
    cc_edge_percent: float  # макс. чистый доход с CryptoCards, %
    markup_rub_default: float  # черновик курса: Rapira + N ₽
    amount_tier_30k: float
    amount_tier_40k: float
    amount_discount_30k: float  # −N ₽ к курсу при сумме > 30к
    amount_discount_40k: float  # −N ₽ к курсу при сумме > 40к
    min_margin_percent: float  # мин. маржа при сумме ≤ 40к
    min_margin_percent_40k: float  # мин. маржа при сумме > 40к
    # Вторая нога курса: bybit_sber20 (логика CC без логина) | api (кабинет CC)
    cc_rate_source: str
    bybit_payment_id: str
    bybit_side: str
    bybit_ad_index: int
    bybit_amount: str

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
    auth = os.getenv("CRYPTOCARDS_AUTHORIZATION", "").strip().strip('"').strip("'")
    token = os.getenv("CRYPTOCARDS_TOKEN", "").strip().strip('"').strip("'")
    ukey = os.getenv("CRYPTOCARDS_UKEY", "").strip().strip('"').strip("'")
    if auth.lower().startswith("authorization:"):
        auth = auth.split(":", 1)[1].strip()
    # CryptoCards фронт шлёт x-token = localStorage.token (не Authorization Bearer).
    if not token and auth:
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else auth

    return Settings(
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        database_path=Path(db),
        admin_ids=_parse_id_set(os.getenv("ADMIN_IDS", "")),
        support_ids=_parse_id_set(os.getenv("SUPPORT_IDS", "")),
        staff_chat_id=_parse_optional_int(os.getenv("STAFF_CHAT_ID", "")),
        support_contact=os.getenv("SUPPORT_CONTACT", "Georgina771").strip().lstrip("@"),
        usdt_rate_rub=float(os.getenv("USDT_RATE_RUB", "90")),
        spread_percent=float(os.getenv("SPREAD_PERCENT", "2")),
        min_amount_rub=float(os.getenv("MIN_AMOUNT_RUB", "3000")),
        max_amount_rub=float(os.getenv("MAX_AMOUNT_RUB", "150000")),
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
        rate_formula=os.getenv("RATE_FORMULA", "cc").strip().lower(),
        target_income_percent=float(os.getenv("TARGET_INCOME_PERCENT", "1.25")),
        rate_refresh_sec=int(os.getenv("RATE_REFRESH_SEC", "60")),
        rate_timeout_sec=float(os.getenv("RATE_TIMEOUT_SEC", "15")),
        cryptocards_api_url=os.getenv(
            "CRYPTOCARDS_API_URL", "https://cryptocards.ws/api/account"
        ).strip(),
        cryptocards_authorization=auth,
        cryptocards_token=token,
        cryptocards_ukey=ukey,
        cryptocards_cookie=os.getenv("CRYPTOCARDS_COOKIE", "").strip(),
        cryptocards_rate_field=os.getenv("CRYPTOCARDS_RATE_FIELD", "rate").strip()
        or "rate",
        cc_edge_percent=float(os.getenv("CC_EDGE_PERCENT", "2")),
        markup_rub_default=float(os.getenv("MARKUP_RUB_DEFAULT", "1")),
        amount_tier_30k=float(os.getenv("AMOUNT_TIER_30K", "30000")),
        amount_tier_40k=float(os.getenv("AMOUNT_TIER_40K", "40000")),
        amount_discount_30k=float(os.getenv("AMOUNT_DISCOUNT_30K", "0.2")),
        amount_discount_40k=float(os.getenv("AMOUNT_DISCOUNT_40K", "0.3")),
        min_margin_percent=float(os.getenv("MIN_MARGIN_PERCENT", "1")),
        min_margin_percent_40k=float(os.getenv("MIN_MARGIN_PERCENT_40K", "0.5")),
        cc_rate_source=os.getenv("CC_RATE_SOURCE", "bybit_sber20").strip().lower(),
        bybit_payment_id=os.getenv("BYBIT_PAYMENT_ID", "585").strip() or "585",
        bybit_side=os.getenv("BYBIT_SIDE", "1").strip() or "1",
        bybit_ad_index=int(os.getenv("BYBIT_AD_INDEX", "20")),
        bybit_amount=os.getenv("BYBIT_AMOUNT", "").strip(),
    )
