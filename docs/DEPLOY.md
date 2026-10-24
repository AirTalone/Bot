# Деплой: от нуля до живого бота

Цель: бот в Docker на VPS, Postgres без порта наружу, рестарт после ребута, бэкап, firewall.

Это **не** юридическая инструкция. Секреты только на сервере.

## 0. Перед началом

- VPS под бот (Ubuntu 22.04+), отдельно от ноды Xray по возможности  
- Домен нужен только если позже включите HTTPS webhook / публичный health; для polling Telegram **домен не обязателен**  
- Токен `@BotFather`, ваши `ADMIN_IDS`, реквизиты QR, (опц.) Marzban API  

Артефакты в репо: `docker-compose.prod.yml` (= `compose.prod.yml`), `deploy/`, `scripts/`.

---

## 15 команд (короткий путь)

На свежем VPS под пользователем с sudo (потом перейдёте на `deploy`):

```bash
# 1) пакеты
sudo apt update && sudo apt install -y ca-certificates curl git ufw

# 2) Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
# перелогиньтесь, чтобы группа docker применилась

# 3) пользователь приложения
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG docker deploy

# 4) код
sudo mkdir -p /opt/vpn-bot && sudo chown deploy:deploy /opt/vpn-bot
sudo -u deploy git clone https://github.com/AirTalone/Bot.git /opt/vpn-bot
cd /opt/vpn-bot
sudo -u deploy git checkout <ваша-релизная-ветка-или-tag>

# 5) env только на сервере
sudo -u deploy cp deploy/env.prod.example .env
sudo -u deploy chmod 600 .env
sudo -u deploy "${EDITOR:-nano}" .env
# обязательны: BOT_TOKEN, ADMIN_IDS, PAYMENT_DETAILS, POSTGRES_PASSWORD

# 6) firewall (SSH не забудьте открыть до enable)
sudo ./deploy/ufw-setup.sh

# 7) поднять prod-стек
sudo -u deploy ./scripts/deploy_prod.sh

# 8) статус
sudo -u deploy docker compose -f compose.prod.yml ps

# 9) логи
sudo -u deploy docker compose -f compose.prod.yml logs -f bot

# 10) systemd (автостарт после reboot)
sudo cp deploy/vpnbot.service /etc/systemd/system/vpnbot.service
sudo systemctl daemon-reload
sudo systemctl enable --now vpnbot.service

# 11) первый бэкап
sudo -u deploy ./scripts/backup_postgres.sh /opt/vpn-bot/backups

# 12) cron бэкапа (UTC 03:15)
echo '15 3 * * * deploy cd /opt/vpn-bot && ./scripts/backup_postgres.sh /opt/vpn-bot/backups >>/var/log/vpnbot-backup.log 2>&1' | sudo tee /etc/cron.d/vpnbot-backup
sudo chmod 644 /etc/cron.d/vpnbot-backup

# 13) смоук в Telegram: /start от админа и от тестового юзера

# 14) (опц.) панель: docs/MARZBAN.md → PANEL_ENABLED=true → recreate bot

# 15) чеклист: docs/GO_LIVE.md — все пункты зелёные перед публичным анонсом
```

---

## Compose-файлы

| Файл | Назначение |
| --- | --- |
| `docker-compose.yml` | dev: Postgres с портом на хост |
| `compose.prod.yml` / `docker-compose.prod.yml` | prod: Postgres только во внутренней сети |

```bash
./scripts/deploy_prod.sh
# эквивалент: docker compose -f compose.prod.yml up -d --build
```

`.env` читает Compose из каталога проекта. Файл **не** коммитить (см. `.gitignore`). На сервере можно держать копию-источник как `.env.prod` с правами `600` и симлинк/копию в `.env`.

---

## TLS / Caddy (опционально)

Для текущего polling HTTPS **не нужен**. Caddy пригодится, если:

- повесите отдельный health/status endpoint;  
- перейдёте на Telegram webhook;  
- отдаёте свой домен рядом с ботом.

Пример: `deploy/Caddyfile.example`. Поднимайте Caddy отдельно от compose бота или добавьте сервис сами.

---

## Firewall

`deploy/ufw-setup.sh` открывает SSH + (опц.) 80/443.  
Postgres и бот наружу не торчат.  
Порты Xray — на VPS **панели/ноды**, не обязательно на VPS бота. См. `docs/MARZBAN.md`.

---

## Systemd

Юнит `deploy/vpnbot.service` делает `docker compose -f compose.prod.yml up -d` при boot и `stop` при stop.  
Политика контейнеров уже `restart: unless-stopped`.

```bash
sudo systemctl status vpnbot
sudo journalctl -u vpnbot -n 50
```

---

## Мягкий запуск → публичный

См. полный чеклист: [`docs/GO_LIVE.md`](GO_LIVE.md).

Кратко: 5–10 друзей → 48 часов багов → бэкап restore drill → потом анонс.

---

## Связанные документы

- Панель: `docs/MARZBAN.md`  
- Бэкапы: `docs/BACKUP.md`  
- Инциденты: `docs/RUNBOOK.md`  
- Надёжность: `docs/RELIABILITY.md`  
- После запуска: `docs/OPS.md`  

