# Telegram-бот: ссылка → QR в стиле СБП

Пришлите боту ссылку вида `https://qr.nspk.ru/...` — он ответит PNG QR-кодом в фирменном цвете СБП (`#1d1346`) на белом фоне со скруглёнными углами.

Никаких платных API: QR строится локально из самой ссылки (в QR СБП как раз и закодирован этот URL).

## Быстрый старт (бесплатно)

### 1. Создайте бота в Telegram

1. Откройте [@BotFather](https://t.me/BotFather)
2. Команда `/newbot` → задайте имя и username
3. Скопируйте токен вида `123456:ABC-DEF...`

### 2. Запустите локально

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# впишите BOT_TOKEN=... в файл .env

python bot.py
```

Напишите боту любую ссылку — получите картинку QR.

### 3. Без Telegram (один файл)

```bash
python generate_once.py "https://qr.nspk.ru/AD101055EDK5J0E099CQ1IGD7IAVBQK0" qr.png
```

## Как это работает

Ссылка НСПК уже содержит всё нужное для оплаты. Бот:

1. достаёт URL из сообщения;
2. кодирует его в QR (ISO/IEC 18004);
3. красит модули в официальный фиолетовый СБП `#1d1346`;
4. добавляет белый «quiet zone» и скруглённую рамку;
5. присылает PNG в чат.

## Бесплатный хостинг (чтобы бот работал 24/7)

Нужен любой сервер, где крутится `python bot.py` или Docker-контейнер.

Варианты без оплаты / с бесплатным тарифом:

| Куда | Как |
|------|-----|
| Свой ПК / ноутбук | Просто держите `python bot.py` запущенным |
| [Railway](https://railway.app) / [Render](https://render.com) / [Fly.io](https://fly.io) | Залейте репозиторий, задайте env `BOT_TOKEN`, команда старта `python bot.py` |
| VPS (Timeweb, Selectel и т.п.) | `docker build -t sbp-qr-bot . && docker run -e BOT_TOKEN=... sbp-qr-bot` |

Docker:

```bash
docker build -t sbp-qr-bot .
docker run --rm -e BOT_TOKEN=123456:ABC... sbp-qr-bot
```

> На бесплатных PaaS иногда «засыпают» веб-сервисы. Для Telegram-бота лучше режим **worker** / background process (long polling), а не web-hook на засыпающем HTTP-сервисе.

## Структура

```
bot.py            — Telegram-бот (aiogram 3)
qr_generator.py   — генерация QR в стиле СБП
generate_once.py  — генерация одного PNG из CLI
requirements.txt
Dockerfile
.env.example
```

## Зависимости

- Python 3.10+
- `aiogram` — Telegram Bot API
- `qrcode` + `Pillow` — картинка QR
- `python-dotenv` — токен из `.env`

## Безопасность

- Не публикуйте `BOT_TOKEN` в git (файл `.env` уже в `.gitignore`)
- Бот не хранит ссылки и не ходит во внешние платные сервисы
