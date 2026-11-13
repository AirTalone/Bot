# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Telegram bot (aiogram 3, Python 3.12) for exchanging RUB → USDT through manually processed orders. Three roles: **client** (creates order, pays, uploads receipt), **support** (`SUPPORT_IDS`: issues payment requisites, reviews receipts, adjusts rate), **admin** (`ADMIN_IDS`: sends USDT manually and records TxID; admins also have all support rights via `Settings.is_support`). All user-facing text, comments and docs are in Russian — keep it that way.

## Commands

```bash
pip install -r requirements.txt
cp .env.example .env          # fill BOT_TOKEN, ADMIN_IDS, SUPPORT_IDS
python bot.py                 # run (long polling)
# Settings file is chosen by ENV_FILE (default .env), read with encoding utf-8-sig (Notepad BOM-safe).
# Local test env on Windows — double-click start_test.bat:
#   start_test.bat is a thin ASCII-only launcher → python scripts/start_test.py, which
#   creates .venv, installs deps, copies .env.test.example → .env.test (opens Notepad on first run),
#   then runs bot.py with ENV_FILE=.env.test (separate test bot token, DB in data/test/, mock receipts)

# Tests (stdlib unittest, no pytest config)
python -m unittest test_qr_generator.py test_exchange.py -v
python -m unittest test_exchange.ClientQuoteTests.test_amount_discounts -v   # single test

# Live diagnostics against real rate sources (need network / .env)
python scripts/smoke_quote.py          # Rapira + CC → computed quote
python scripts/check_cc_rate.py [--diagnose]   # Bybit P2P / Rapira reachability
python scripts/test_cc_auth.py         # check CRYPTOCARDS_* creds without printing secrets

python generate_once.py <sbp-url> [out.png]   # standalone SBP QR generator
```

`test_qr_generator.test_png_looks_like_sbp_card` needs `opencv-python` (not in requirements) and fails without it — unrelated to the bot. On Windows, `tzdata` (in requirements with a `win32` marker) is required, otherwise `ZoneInfo("Europe/Moscow")` crashes at import.

Windows `.bat` files must be **ASCII-only with CRLF line endings** — cmd misparses UTF-8/Cyrillic lines (even with `chcp 65001`) and executes garbage fragments. Put any logic/Russian text in a Python script and call it from the `.bat`.

No linter/formatter is configured. Docker: `docker build -t exchange-bot .` — note the Dockerfile copies only `bot.py`, `qr_generator.py`, `generate_once.py` and `exchange/`; new top-level modules must be added there. VPS deploy is systemd-based (`deploy/install_on_vps.sh`, `scripts/update_rate_env_on_vps.sh`, app dir `/opt/exchange-bot`, branch `cursor/exchange-bot-flow-2782`).

## Architecture

**Wiring (`bot.py`)**: loads `Settings` from env → opens `Database` (orders) and `RateSampleStore` (separate `rate_samples.db` next to the orders DB) → builds receipt checker, `RateService`, `OrderService` → packs them into `AppContext`. `ContextMiddleware` injects `ctx`, `settings`, `orders`, `db`, `rates` into every handler's kwargs — handlers receive dependencies by parameter name. Two background loops run alongside polling: `expire_loop` (60s, expires overdue `awaiting_payment` orders and notifies clients) and `rates_loop` (`RATE_REFRESH_SEC`, min 15s).

**Layering**:
- `exchange/statuses.py` — single source of truth for the order state machine: `OrderStatus`, `ALLOWED_TRANSITIONS`, RU labels, and the status sets for support/admin queues and "active client order". Changing flow starts here.
- `exchange/services.py` (`OrderService`) — all domain operations and validation; raises `OrderError` with a user-facing Russian message which handlers show verbatim. **`_transition()` only validates** against `ALLOWED_TRANSITIONS`; the actual status write is done by the subsequent `db.update_fields(status=...)` call, so new operations must do both. `cancel()` uses a looser check (allows from `expired`).
- `exchange/db.py` — raw aiosqlite, one `orders` table. Schema is `CREATE TABLE IF NOT EXISTS` with **no migrations**: adding a column requires an explicit `ALTER TABLE` path for existing DBs. `update_fields(**kw)` is the generic writer (converts `OrderStatus` and `extra` → `extra_json`). A client may have only one order in `CLIENT_VISIBLE_ACTIVE` statuses. Public IDs look like `EX-XXXXXX`.
- `exchange/models.py` — `Order` dataclass; `has_usdt_address` (USDT address is optional at creation and required before payout); `usdt_exact` (stored payout amount without trailing zeros).
- `exchange/staff_card.py` — `staff_card(order, owner=..., show_owner=...)`: the staff (support/admin) order card, "list with icons" style, used both in the work group and in staff DMs. Keyboards: `keyboards.staff_order_kb()` (one main action per status on top, secondary buttons two per row); `support_order_kb` / `staff_card_kb` are thin wrappers (DM / group).
- `exchange/handlers/` — one aiogram `Router` per role; registration order in `handlers/__init__.py` matters, `fallback` must stay last (it catches any message in default state and shows the menu). `qr_tool.py` exists but is **not registered** (SBP QR flow is disabled in the exchange flow).
- `exchange/keyboards.py` — inline keyboards are built per order status; callback data format is `<scope>:<action>:<order_id>` (`client:`, `support:`, `admin:`, `wallet:`), matched via `F.data.startswith(...)`. Role checks are done inside each handler (`_require_support` / `_require_admin`), not by filters.
- `exchange/staff_panel.py` + `handlers/staff.py` — staff work group (`STAFF_CHAT_ID`; unset → old behaviour, DM notifications). `OrderService.on_change` (set via the `@_notifies` decorator on every mutating method) calls `StaffPanel.sync(order)`, which keeps **one card per order** in the group: edited in place, but deleted + re-sent ("bumped", so people get a notification) when the status enters `ATTENTION_STATUSES`. Card message ids live in table `staff_cards`; order ownership ("🙋 Взять", `staff:take/release`) in `order_owners` — both separate tables, so no migration of `orders`. Support actions call `panel.ensure_owner()` (auto-takes a free order; others are refused, admins bypass). Any text input started from a group button goes to the staff member's **private chat** via `start_staff_input()` / `dm_state()` (FSM key for the DM). All message routers except `staff` are filtered to private chats in `handlers/__init__.py`. `/stats` (`exchange/stats.py`) aggregates today / 7 / 30 days (Moscow), `/chatid` prints the group id.
- `exchange/client_card.py` — `client_card(order)`: the client-facing order text (status title + "what's next" hint per status, requisites block with MSK deadline, HTML-escaped user input). Two styles switched by `CLIENT_CARD_STYLE` (`minimal` | `steps`). All client messages/notifications use it; staff see `staff_card()` instead.
- `exchange/screen.py` — "one screen" UX: a bot-session request middleware deletes the bot's messages from the user's previous step (plus the message whose button was pressed) after the first send of a new step. A step = one incoming update in a private chat (tracked via a ContextVar set by an outer update middleware). The user's own text message of the step is deleted too (documents/photos — receipts — are kept). Not touched: notifications to other chats / from background loops, and the latest message carrying a `ReplyKeyboardMarkup` (deleting it would remove the bottom menu keyboard). Tracking is in memory. Handlers don't need to do anything — just send messages as usual.
- `exchange/states.py` — FSM states. Storage is `MemoryStorage`, so in-progress dialogs are lost on restart. Admin dispute/cancel reuses `SupportNote` state, whose finishing handler lives in `support.py`.

**Rates (`exchange/rates/`)**: `RateService.refresh()` fetches Rapira (public API, aiohttp with curl `--http1.1` fallback) and the "CryptoCards leg", then stores an immutable `RateSnapshot`. The CC leg depends on `CC_RATE_SOURCE`: `bybit_sber20` (default — N-th Bybit P2P Sberbank ad, sampled into `RateSampleStore` and averaged per Moscow day) or `api` (CryptoCards account API with `x-token`/`x-ukey`). On fetch failure the previous good values are kept rather than falling back to `USDT_RATE_RUB`. Pricing logic is pure functions in `pricing.py`:
- `spread` formula (default): client rate = Rapira + `MARKUP_RUB_DEFAULT` − amount discount (>30k / >40k tiers); CC is used only as purchase cost: `cost = CC × (1 − CC_EDGE_PERCENT/100)`; margin is checked against `MIN_MARGIN_PERCENT` (≤40k) / `MIN_MARGIN_PERCENT_40K`. Low margin does not block order creation — it only sets `margin_ok=False`, which changes support's buttons/warnings.
- `max|min|avg` are legacy formulas (`combine_rates_legacy` + `SPREAD_PERCENT`).
- `RATE_MODE=static` uses `USDT_RATE_RUB × (1+SPREAD_PERCENT%)` with the same amount discounts.

The quote at order creation is persisted into `orders.extra_json` (`RateQuote.to_extra()`: rapira, cryptocards, effective_cost, margin_percent, margin_ok, …); support's "Изменить курс" recomputes margin via `reevaluate_margin` and updates `rate`, `amount_usdt` and `extra`.

**Receipt check (`exchange/receipt/`)**: `ReceiptChecker` protocol; `factory.build_receipt_checker` picks by `RECEIPT_PROVIDER`: `mock` (fails if filename/mime contains `fail` or bytes contain `FAIL_RECEIPT`) or `http`/`fraudex`/`api` (multipart POST to `RECEIPT_API_URL`, tolerant success detection over several response shapes). A failed or errored check moves the order to `receipt_rejected`, never blocks it — support can still approve manually. `RECEIPT_FAIL_OPEN_TO_SUPPORT` is parsed into Settings but currently unused.

## Conventions / gotchas

- `Settings` is a frozen dataclass without defaults: adding a field means updating `load_settings()`, `.env.example`, and the `_settings()` helper in `test_exchange.py` (otherwise tests break).
- Telegram messages use `parse_mode="HTML"`; notifications to other users are wrapped in `try/except` + `logger.exception` so one failed send doesn't break the flow.
- Datetimes are stored as UTC ISO strings (`models.iso` / `parse_dt`); daily rate averages use Europe/Moscow.
