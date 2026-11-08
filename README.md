# Telegram-бот: обмен RUB → USDT

Заявки с ручной выдачей реквизитов (с площадки выплат), загрузкой чека, автопроверкой (Fraudex / HTTP / mock) и выплатой USDT администратором.

Выдача QR / ссылок СБП в обменном потоке сейчас отключена.

## Поток заявки

```
Клиент создаёт заявку
        ↓
 awaiting_requisites     ← саппорт ищет реквизиты на площадке выплат
        ↓
 awaiting_payment        ← клиенту ушли реквизиты
        ↓
 checking_receipt        ← клиент загрузил чек, идёт автопроверка
        ↓
   ┌────┴────┐
   ↓         ↓
awaiting_    receipt_
support_     rejected     ← можно залить другой чек или саппорт берёт вручную
review
   ↓
 awaiting_payout         ← саппорт одобрил оплату
        ↓
 completed               ← админ отправил USDT и вписал TxID
```

Дополнительно: `cancelled`, `expired` (таймер после выдачи реквизитов), `disputed`.

### Статусы

| Статус | Кто действует | Что происходит |
|---|---|---|
| `awaiting_requisites` | Саппорт | Заявка создана. Под заявку ищутся реквизиты на площадке выплат |
| `awaiting_payment` | Клиент | Реквизиты выданы. Клиент платит и готовит чек |
| `checking_receipt` | Бот | Чек отправлен в сервис автопроверки |
| `receipt_rejected` | Клиент / саппорт | Автопроверка (или саппорт) отклонила чек |
| `awaiting_support_review` | Саппорт | Автопроверка ок — нужно ручное одобрение |
| `awaiting_payout` | Админ | Оплата подтверждена — админ шлёт USDT |
| `completed` | — | Выплата зафиксирована (есть TxID) |
| `cancelled` | Клиент / саппорт / админ | Отменена |
| `expired` | Бот | Истёк TTL оплаты |
| `disputed` | Админ | Спор, ручная разборка |

### Роли

- **Клиент** — создаёт заявку, получает реквизиты, грузит чек.
- **Саппорт** (`SUPPORT_IDS`) — вставляет реквизиты с площадки, смотрит автопроверку, одобряет/отклоняет.
- **Админ** (`ADMIN_IDS`) — только он отмечает выплату USDT (вывод средств руками). Админ также имеет права саппорта.

## Быстрый старт

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# BOT_TOKEN, ADMIN_IDS, SUPPORT_IDS, USDT_RATE_RUB

python bot.py
```

Тесты:

```bash
python -m unittest test_qr_generator.py test_exchange.py -v
```

## Команды

| Команда | Кто | Назначение |
|---|---|---|
| `/exchange` | клиент | Новая заявка |
| `/orders` | клиент | Мои заявки |
| `/rate` | все | Курс и лимиты |
| `/support` | саппорт/админ | Очереди: реквизиты / проверка / в оплате |
| `/admin` | админ | Очереди: выплата USDT / споры |

## Проверка чеков (Fraudex и аналоги)

Публичного стабильного API у Fraudex в открытом доступе нет. В боте сделан провайдер:

1. `RECEIPT_PROVIDER=mock` — для разработки (имя файла с `fail` → reject).
2. `RECEIPT_PROVIDER=http` (или `fraudex`) — POST multipart на `RECEIPT_API_URL` с полями `file`, `api_key`, `price` / `expected_amount`, `user_id`, `order_id`.

Когда будет ключ/URL от Fraudex или другого сервиса — пропиши в `.env`:

```env
RECEIPT_PROVIDER=http
RECEIPT_API_URL=https://...
RECEIPT_API_KEY=...
```

Если ответ сервиса не распознан как success — статус `receipt_rejected`, саппорт всё равно видит заявку и может одобрить вручную.

## Docker

```bash
docker build -t exchange-bot .
docker run --rm --env-file .env -v exchange-data:/app/data exchange-bot
```

## Структура

```
bot.py                 — точка входа
exchange/
  statuses.py          — статусы и переходы
  config.py / db.py    — настройки и SQLite
  services.py          — бизнес-логика
  receipt/             — mock + HTTP (Fraudex-совместимый адаптер)
  handlers/            — клиент / саппорт / админ
```
