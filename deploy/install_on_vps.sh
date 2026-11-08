#!/usr/bin/env bash
# Установка обменного бота на Ubuntu/Debian VPS (под root или с sudo).
#
# Пример:
#   export BOT_TOKEN='123:ABC'
#   export ADMIN_IDS='111'
#   export SUPPORT_IDS='111'
#   export USDT_RATE_RUB='90'
#   bash deploy/install_on_vps.sh
#
# Или одной строкой после clone:
#   BOT_TOKEN='...' ADMIN_IDS='...' SUPPORT_IDS='...' bash deploy/install_on_vps.sh
set -euo pipefail

APP_DIR=/opt/exchange-bot
SERVICE=exchange-bot
REPO_URL="${REPO_URL:-https://github.com/AirTalone/Bot.git}"
REPO_BRANCH="${REPO_BRANCH:-cursor/exchange-bot-flow-2782}"

if [[ -z "${BOT_TOKEN:-}" ]]; then
  echo "Задайте BOT_TOKEN, ADMIN_IDS и SUPPORT_IDS, например:"
  echo "  export BOT_TOKEN='123:ABC'"
  echo "  export ADMIN_IDS='111111111'"
  echo "  export SUPPORT_IDS='111111111'"
  echo "  bash deploy/install_on_vps.sh"
  exit 1
fi

if [[ -z "${ADMIN_IDS:-}" ]]; then
  echo "Задайте ADMIN_IDS (ваш Telegram ID)."
  exit 1
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Запустите скрипт от root (или через sudo)."
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip git curl ca-certificates

mkdir -p "$APP_DIR"
cd "$APP_DIR"

if [[ ! -f bot.py ]]; then
  echo "Код не найден в $APP_DIR — клонирую $REPO_BRANCH..."
  rm -rf /tmp/exchange-bot-src
  git clone --depth 1 --branch "$REPO_BRANCH" "$REPO_URL" /tmp/exchange-bot-src
  # Копируем содержимое репозитория в APP_DIR
  shopt -s dotglob
  cp -a /tmp/exchange-bot-src/* "$APP_DIR"/
  shopt -u dotglob
  rm -rf /tmp/exchange-bot-src
fi

if [[ ! -f bot.py ]]; then
  echo "После клонирования всё ещё нет bot.py — проверьте REPO_URL / REPO_BRANCH"
  exit 1
fi

mkdir -p "$APP_DIR/data"

python3 -m venv .venv
.venv/bin/pip install -q -U pip
.venv/bin/pip install -q -r requirements.txt

umask 077
{
  printf 'BOT_TOKEN=%s\n' "$BOT_TOKEN"
  printf 'ADMIN_IDS=%s\n' "$ADMIN_IDS"
  printf 'SUPPORT_IDS=%s\n' "${SUPPORT_IDS:-$ADMIN_IDS}"
  printf 'USDT_RATE_RUB=%s\n' "${USDT_RATE_RUB:-90}"
  printf 'SPREAD_PERCENT=%s\n' "${SPREAD_PERCENT:-2}"
  printf 'MIN_AMOUNT_RUB=%s\n' "${MIN_AMOUNT_RUB:-1000}"
  printf 'MAX_AMOUNT_RUB=%s\n' "${MAX_AMOUNT_RUB:-500000}"
  printf 'PAYMENT_TTL_MINUTES=%s\n' "${PAYMENT_TTL_MINUTES:-20}"
  printf 'DATABASE_PATH=%s\n' "${DATABASE_PATH:-$APP_DIR/data/exchange.db}"
  printf 'RECEIPT_PROVIDER=%s\n' "${RECEIPT_PROVIDER:-mock}"
} > .env
chmod 600 .env

cat > /etc/systemd/system/${SERVICE}.service << UNIT
[Unit]
Description=RUB to USDT Exchange Telegram Bot
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

echo
echo "OK: сервис ${SERVICE} установлен."
echo "Логи: journalctl -u ${SERVICE} -f"
echo "Стоп: systemctl stop ${SERVICE}"
echo "Старт: systemctl start ${SERVICE}"
