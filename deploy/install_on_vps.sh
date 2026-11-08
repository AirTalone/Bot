#!/usr/bin/env bash
# Запуск НА сервере (под root)
set -euo pipefail

APP_DIR=/opt/exchange-bot
SERVICE=exchange-bot

if [[ -z "${BOT_TOKEN:-}" ]]; then
  echo "Задайте BOT_TOKEN (и желательно ADMIN_IDS / SUPPORT_IDS), например:"
  echo "  BOT_TOKEN='123:ABC' ADMIN_IDS='1' SUPPORT_IDS='1,2' bash install_on_vps.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip

mkdir -p "$APP_DIR/data"
cd "$APP_DIR"

if [[ ! -f bot.py ]]; then
  echo "Нет bot.py в $APP_DIR — сначала скопируйте файлы проекта"
  exit 1
fi

python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

umask 077
{
  printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN"
  printf 'ADMIN_IDS=%s\n' "${ADMIN_IDS:-}"
  printf 'SUPPORT_IDS=%s\n' "${SUPPORT_IDS:-}"
  printf 'USDT_RATE_RUB=%s\n' "${USDT_RATE_RUB:-90}"
  printf 'SPREAD_PERCENT=%s\n' "${SPREAD_PERCENT:-2}"
  printf 'DATABASE_PATH=%s\n' "${DATABASE_PATH:-$APP_DIR/data/exchange.db}"
  printf 'RECEIPT_PROVIDER=%s\n' "${RECEIPT_PROVIDER:-mock}"
} > .env
chmod 600 .env

cat > /etc/systemd/system/${SERVICE}.service << UNIT
[Unit]
Description=RUB→USDT Exchange Telegram Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
EnvironmentFile=${APP_DIR}/.env
ExecStart=${APP_DIR}/.venv/bin/python bot.py
Restart=always
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now ${SERVICE}
systemctl --no-pager --full status ${SERVICE} || true
echo "OK: service ${SERVICE} installed"
