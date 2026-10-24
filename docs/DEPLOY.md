# Деплой (фаза 1)

Минимум: Docker + Postgres. Бот по-прежнему с ручной оплатой по QR.

## Локально / один VPS

1. Скопируй env:

```bash
cp .env.example .env
```

2. Заполни минимум:

- `BOT_TOKEN`
- `ADMIN_IDS`
- `PAYMENT_DETAILS`
- `POSTGRES_PASSWORD` (сильный пароль)

3. Подними стек:

```bash
docker compose up -d --build
docker compose logs -f bot
```

Сервисы:

- `db` — Postgres 16
- `migrate` — `alembic upgrade head` + seed тарифов (один раз за старт)
- `bot` — polling aiogram

## Без Docker (SQLite)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# DATABASE_URL=sqlite+aiosqlite:///data/bot.db
python -m bot
```

## Миграции вручную

```bash
export DATABASE_URL=postgresql+asyncpg://vpnbot:PASS@127.0.0.1:5432/vpnbot
alembic upgrade head
python -m bot.seed
```

## Проверка

```bash
pip install -r requirements-dev.txt
ruff check bot tests alembic
python -m pytest -q
```

Дальше по плану: `docs/PRODUCT_ROADMAP.md` → фаза 2 (панель VPN).
