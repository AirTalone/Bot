# Marzban: установка панели (фаза 2)

Панель выдаёт subscription URL. Бот после «Подтвердить» создаёт/продлевает пользователя через API.

Это **не** юридическая инструкция. Серверы нод обычно вне РФ; админку панели не светите в открытый интернет без TLS и ограничений.

## 1. VPS под панель

Минимум ориентировочно: 1 vCPU, 1–2 ГБ RAM, Ubuntu 22.04+.  
Отдельно от бота — лучше. На одном VPS с ботом можно только для теста.

## 2. Установка Marzban

Официальный скрипт (проверяйте URL в актуальной доке Marzban):

```bash
sudo bash -c "$(curl -sL https://github.com/Gozargah/Marzban-scripts/raw/master/marzban.sh)" @ install
```

Создайте sudo-admin:

```bash
marzban cli admin create --sudo
```

Откройте dashboard (по умолчанию `:8000/dashboard/`), сразу смените пароль.

## 3. Inbound

В Xray-конфиге панели настройте хотя бы один рабочий inbound, например **VLESS + REALITY**.  
Проверьте руками: тестовый пользователь → импорт в клиент → трафик идёт.

Запомните **теги inbound**, если хотите ограничить выдачу не всеми inbounds:

```json
{"vless": ["VLESS TCP REALITY"]}
```

Пустой `PANEL_INBOUNDS_JSON={}` = все inbounds протокола.

## 4. API для бота

В `.env` бота:

```env
PANEL_ENABLED=true
PANEL_PROVIDER=marzban
PANEL_BASE_URL=https://panel.example.com
PANEL_USERNAME=admin
PANEL_PASSWORD=strong-password
PANEL_PROXIES_JSON={"vless": {}}
PANEL_INBOUNDS_JSON={}
```

`PANEL_BASE_URL` — корень панели **без** хвоста `/dashboard`.  
Бот ходит на `POST /api/admin/token` и `POST/PUT /api/user`.

## 5. Безопасность панели

- HTTPS (Caddy/Nginx) на домен панели
- сильный пароль admin, без дефолтов
- firewall: наружу порты Xray + 443; admin UI по возможности только с вашего IP / VPN / Cloudflare Access
- бэкап `/var/lib/marzban` (или том Docker) по cron offsite
- не коммитьте `PANEL_PASSWORD` в git

## 6. Проверка связки с ботом

1. `PANEL_ENABLED=true`, бот перезапущен  
2. Создайте тестовую заявку → «Я оплатил»  
3. В `/admin` нажмите «Подтвердить и выдать из панели»  
4. Пользователь получает `subscription_url`  
5. Импорт в клиент работает  

Если панель недоступна — заявка остаётся на проверке, можно «Вставить ссылку вручную».

## 7. Имена пользователей в панели

Бот создаёт username вида `tg<telegram_id>` (например `tg42`).  
Повторная покупка того же Telegram-аккаунта **продлевает** expire от `max(now, current_expire)`.

## 8. Лимиты устройств / мультинода (ops)

Marzban сам по себе слабее Remnawave по HWID. Практичные рычаги:

- один пользователь = один subscription URL; не плодите дубликаты вручную;
- лимиты на уровне inbound/ноды и разумный `data_limit`, если нужен;
- вторая нода: добавляйте в Marzban Node, когда упираетесь в канал/CPU — боту менять код не нужно, он выдаёт тот же API user.

Если критичны device limits / вебхуки — позже смотрите Remnawave; сейчас стек заточен под Marzban.

## 9. Chaos: панель выключена 5 минут

Ожидаемое поведение бота:

- polling и QR-оплата продолжают работать;
- автовыдача пишет ошибку, заявка остаётся `pending_review`;
- админ может вставить ссылку вручную или повторить confirm после подъёма панели.

См. `docs/RUNBOOK.md`.

## Дальше

`docs/PRODUCT_ROADMAP.md`, `docs/RELIABILITY.md`.
