# Деплой

Минимум: Docker + Postgres. Оплата: QR и опционально Telegram Stars.

## Dev / один VPS (порты Postgres открыты)

```bash
cp .env.example .env
# BOT_TOKEN, ADMIN_IDS, PAYMENT_DETAILS, POSTGRES_PASSWORD
docker compose up -d --build
docker compose logs -f bot
docker compose ps
```

Сервисы: `db`, `migrate` (один раз), `bot` (polling + healthcheck по heartbeat).

## Prod

```bash
cp .env.example .env
# секреты только на сервере
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps
./scripts/backup_postgres.sh ./backups
```

В prod Postgres **не** публикуется на хост. Логи JSON: `LOG_JSON=true`.  
Опционально: `SENTRY_DSN=...`, `PANEL_ENABLED=true`, `STARS_ENABLED=true`.

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

Только forward. Откат — через restore дампа (`docs/BACKUP.md`).

## Проверка

```bash
pip install -r requirements-dev.txt
ruff check bot tests alembic
python -m pytest -q
```

Панель: `docs/MARZBAN.md`. Инциденты: `docs/RUNBOOK.md`. Надёжность: `docs/RELIABILITY.md`.
