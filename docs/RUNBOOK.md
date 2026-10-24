# Runbook инцидентов

Кратко: симптом → что сделать. Не юридическая инструкция.

## Панель лежит / timeout Marzban

Симптомы: в `/admin` «Панель недоступна», в audit `panel_error`, Stars ушли в pending.

1. Не паникуйте: заявки остаются `pending_review`, QR/ручная ссылка работают.
2. Проверьте `PANEL_BASE_URL`, TLS, `curl -I "$PANEL_BASE_URL"`.
3. Логи Marzban / диск / OOM на VPS панели.
4. Пока чините — выдавайте «Вставить ссылку вручную» или включите техработы в `/admin`.
5. После подъёма панели: повторите «Подтвердить и выдать из панели».

Chaos-ожидание: 5 минут без панели бот **не** должен падать; только деградация автовыдачи.

## Telegram 429 / RetryAfter

Симптомы: рассылка тормозит, в логах flood control.

1. Увеличьте `BROADCAST_DELAY_SECONDS` (например `0.1`–`0.2`).
2. Не запускайте второй broadcast параллельно.
3. Бот уже ждёт `retry_after` в рассылке; остальной polling обычно сам отходит.

## Бот не отвечает / polling умер

1. `docker compose ps` — статус `bot`, healthcheck.
2. `docker compose logs --tail=200 bot`.
3. Heartbeat: файл `HEARTBEAT_PATH` должен обновляться каждые `HEARTBEAT_SECONDS`.
4. `docker compose up -d --force-recreate bot` (`restart: unless-stopped`).
5. Если после рестарта тихо — проверьте `BOT_TOKEN`, сеть до `api.telegram.org`, место на диске.

## Диск полный

Симптомы: Postgres read-only, бот падает на commit, бэкапы не пишутся.

1. `df -h` на VPS бота и панели.
2. Удалите старые логи/образы Docker; не трогайте единственный бэкап.
3. Разгребите `backups/` (скрипт сам ротирует, но offsite важнее).
4. Поднимите сервисы заново, проверьте запись в БД.

## Утечка BOT_TOKEN / PANEL_PASSWORD

1. Немедленно перевыпустите токен у `@BotFather` / смените пароль панели.
2. Обновите `.env` на сервере, `docker compose up -d --force-recreate bot`.
3. Проверьте git history / issues — секреты не должны быть в репо (`gitleaks`/поиск).
4. Запишите audit: кто имел доступ к `.env`.

## Ложные оплаты / спам заявок

1. Включите техработы в `/admin`.
2. Отклоните мусорные заявки; при необходимости `disable` в панели из поиска.
3. Ужесточите `ORDER_COOLDOWN_SECONDS` / `PAID_COOLDOWN_SECONDS`.
