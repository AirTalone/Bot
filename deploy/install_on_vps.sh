#!/usr/bin/env bash
# Запуск НА сервере (под root)
set -euo pipefail

APP_DIR=/opt/sbp-qr-bot
SERVICE=sbp-qr-bot

if [[ -z "${BOT_TOKEN:-}" ]]; then
  echo "Задайте BOT_TOKEN, например:"
  echo "  BOT_TOKEN='123:ABC' bash install_on_vps.sh"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip

mkdir -p "$APP_DIR"
cd "$APP_DIR"

if [[ ! -f bot.py ]]; then
  echo "Нет bot.py в $APP_DIR — сначала скопируйте файлы проекта"
  exit 1
fi

python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

umask 077
printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN" > .env
chmod 600 .env

cat > /etc/systemd/system/${SERVICE}.service << UNIT
[Unit]
Description=SBP QR Telegram Bot
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
