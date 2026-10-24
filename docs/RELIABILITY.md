# Надёжность (фаза 8)

## Что включено в репозитории

| Тема | Где |
| --- | --- |
| Daily Postgres backup / restore | `scripts/backup_postgres.sh`, `scripts/restore_postgres.sh`, `docs/BACKUP.md` |
| Docker restart + healthcheck | `restart: unless-stopped`, heartbeat file, `docker-compose*.yml` |
| Heartbeat / self-ping | `HEARTBEAT_*`, `bot/services/heartbeat.py` |
| JSON logs | `LOG_JSON=true` |
| Sentry | `SENTRY_DSN` (+ `sentry-sdk`) |
| Runbook | `docs/RUNBOOK.md` |
| Нагрузочный smoke | `tests/test_load_orders.py` (100 параллельных create_order) |
| Деградация панели | уже в коде: pending + ручная ссылка; runbook «панель лежит» |

## Осознанно ops/позже

- Лимиты устройств (HWID) — сторона Remnawave / политика нод Marzban; см. `docs/MARZBAN.md`.
- Вторая нода / failover — когда вырастет нагрузка.
- Полный `security-audit` и `parallel-code-review` — перед публичным запуском (скиллы в `.agents/skills/`).

## Рекомендуемый prod-старт

```bash
cp .env.example .env
# заполнить секреты
docker compose -f docker-compose.prod.yml up -d --build
./scripts/backup_postgres.sh ./backups
```
