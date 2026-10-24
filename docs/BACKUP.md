# Бэкапы Postgres

Миграции Alembic — **только вперёд** (`alembic upgrade head`). Откат схемы на проде не используем: восстанавливаем из дампа.

## Daily dump

На хосте с Docker Compose:

```bash
./scripts/backup_postgres.sh ./backups
```

Cron (UTC, каждый день в 03:15):

```cron
15 3 * * * cd /opt/vpn-bot && ./scripts/backup_postgres.sh ./backups >>/var/log/vpnbot-backup.log 2>&1
```

Скрипт держит последние `BACKUP_KEEP` (по умолчанию 14) файлов `vpnbot_*.sql.gz`.

Копируйте архивы offsite (S3/другой VPS/restic) — локальный диск ≠ бэкап.

## Restore drill (раз в месяц)

1. Возьмите свежий `.sql.gz`.
2. На **тестовом** compose (не на боевом без необходимости):

```bash
docker compose up -d db
./scripts/restore_postgres.sh ./backups/vpnbot_YYYYMMDDTHHMMSSZ.sql.gz
docker compose run --rm migrate
```

3. Проверьте: `SELECT count(*) FROM orders;` и смоук `/start` бота на стейдже.
4. Запишите дату drill в календарь/issue.

## Панель Marzban

Отдельно бэкапьте том/данные Marzban (`docs/MARZBAN.md`). Восстановление бота без бэкапа панели не вернёт subscription URL пользователей панели.
