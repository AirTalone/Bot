#!/usr/bin/env bash
# Обновление кода + ключей формулы курса на VPS.
# Запуск на сервере из /opt/exchange-bot:
#   bash scripts/update_rate_env_on_vps.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/exchange-bot}"
BRANCH="${REPO_BRANCH:-cursor/exchange-bot-flow-2782}"
cd "$APP_DIR"

echo "==> git fetch/checkout $BRANCH"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

if [[ ! -f .env ]]; then
  echo "Нет .env в $APP_DIR"
  exit 1
fi

upsert() {
  local key="$1" value="$2"
  if grep -q "^${key}=" .env; then
    sed -i "s|^${key}=.*|${key}=${value}|" .env
  else
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

# Записать ключ, только если его ещё нет (не затирать ваши настройки)
add_if_missing() {
  local key="$1" value="$2"
  if ! grep -q "^${key}=" .env; then
    printf '%s=%s\n' "$key" "$value" >> .env
  fi
}

echo "==> обновляю ключи формулы в .env"
upsert RATE_MODE auto
upsert RATE_FORMULA cc
add_if_missing TARGET_INCOME_PERCENT 1.25
add_if_missing SUPPORT_CONTACT Georgina771
upsert RATE_REFRESH_SEC 60
upsert MARKUP_RUB_DEFAULT 1
upsert CC_EDGE_PERCENT 2
upsert AMOUNT_TIER_30K 30000
upsert AMOUNT_TIER_40K 40000
upsert AMOUNT_DISCOUNT_30K 0.2
upsert AMOUNT_DISCOUNT_40K 0.3
upsert MIN_MARGIN_PERCENT 1
upsert MIN_MARGIN_PERCENT_40K 0.5

if [[ -x .venv/bin/pip ]]; then
  .venv/bin/pip install -q -r requirements.txt
fi

echo "==> smoke_quote"
if ! .venv/bin/python scripts/smoke_quote.py; then
  echo "WARN: smoke_quote упал — всё равно перезапускаю бота"
fi

echo "==> restart exchange-bot"
systemctl restart exchange-bot
systemctl --no-pager --full status exchange-bot | head -20

echo "Готово. В Telegram: /rate и тестовая заявка."
