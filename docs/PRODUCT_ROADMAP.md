# План: от каркаса до боевого VPN-бота

Документ для Владислава. Цель: после выполнения шагов остаётся залить стек на сервер и пользоваться.  
Срез рынка и репозиториев: **24 октября 2026 (Europe/Moscow)**.  
Это **не юридическая консультация** — по лицензиям связи / РКН / 54-ФЗ нужен профильный юрист под вашу схему.

---

## 0. Что уже есть у нас

Репозиторий `AirTalone/Bot` уже умеет:

1. выбор тарифа;
2. QR + код платежа;
3. «Я оплатил»;
4. подтверждение в `/admin`;
5. ручная вставка ссылки доступа + автовыдача Marzban (`PANEL_ENABLED`);
6. UX: /help, FAQ, напоминания об истечении, антиспам;
7. Админка: stats, поиск, CSV, рассылка, техработы, audit;
8. Telegram Stars + QR fallback;
9. Надёжность: бэкапы, heartbeat, Sentry, runbook;
10. pytest на статусы и e2e-флоу без Telegram.

Дальше не «переписывать с нуля чужой магазин», а **дожать свой бот** и подключить панель выдачи.

---

## 1. Карта рынка (что есть сейчас)

### 1.1. Панели (ядро VPN)

| Панель | Сигнал | Когда брать |
| --- | --- | --- |
| **3x-ui** ([MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui), ★~48k) | Быстрый старт, один сервер, активные релизы. Авторы ориентируют на personal use. | Личная нода / MVP на 1 VPS |
| **Marzban** ([Gozargah/Marzban](https://github.com/Gozargah/Marzban), ★~7.5k) | REST API, multi-node, subscription link, встроенный admin Telegram-бот. Темп релизов замедлился, но экосистема жива. | 2–10 нод, API к своему боту |
| **Remnawave** ([remnawave/panel](https://github.com/remnawave/panel)) | Postgres, вебхуки, HWID/device limits, API-first, активная экосистема шоп-ботов. Тяжелее по RAM (~2 ГБ), бывают breaking changes. | Сервис на вырост + биллинг |

**Рекомендация для этого проекта**

- **Фаза A (сейчас → первые продажи):** Marzban **или** Remnawave.  
  - Хотите проще и ближе к Python/API-документации → **Marzban**.  
  - Хотите device limits / вебхуки / рост → **Remnawave**.  
- **3x-ui** — только если сознательно один сервер и готовы к API похуже + «не production» позиции мейнтейнеров.

### 1.2. Готовые шоп-боты (альтернатива «взять чужое»)

| Проект | Панель | Платежи | Заметка |
| --- | --- | --- | --- |
| [remnawave-telegram-shop](https://github.com/Jolymmiels/remnawave-telegram-shop) | Remnawave | YooKassa, Stars, Crypto, Platega… | Зрелый шоп, AGPL |
| [remnashop](https://github.com/snoups/remnashop) | Remnawave | богатый набор | ★~530 |
| Bedolaga / AltShop | Remnawave | много шлюзов + Mini App | тяжёлые комплексы |
| [YadrenoVPN](https://github.com/plushkinv/YadrenoVPN) | 3x-ui | СБП/карты/Stars/crypto | «установи и продавай» |
| [MarzBot](https://github.com/lovehrom/marzbot) | Marzban | Robokassa/crypto | aiogram 3 |
| [VexVPN](https://github.com/rasvetovvv/vexvpn-telegram-vpn) | Marzban | Telegram Stars | Mini App |

**Почему мы не бросаем наш каркас:** у вас уже задана модель «QR вручную → админ подтверждает». Чужие шопы тянут свои платежи, лицензии (часто AGPL) и чужой UX. Их используем как **референс**, а продукт собираем на своём коде + API панели.

### 1.3. Оплата

Реалистичные варианты для RU-аудитории:

1. **Ручной QR/СБП + код** (как сейчас) — минимум зависимостей, максимум ручной работы админа. Хороший старт.
2. **Эквайринг с webhook** (YooKassa / Platega / аналог) — автоподтверждение, нужны ИП/ООО, оферта, часто 54-ФЗ/касса.
3. **Telegram Stars** — просто технически, комиссия Telegram, удобно для digital goods внутри TG.
4. **CryptoBot / crypto** — проще с юрисдикцией серверов, хуже для «обычного» RU-пользователя.

План ниже сначала стабилизирует ручной QR, затем добавляет **автовыдачу из панели**, затем опционально автоплатёж.

### 1.4. Безопасность и условия работы (практика)

Техника:

- панель и бот на разных сетевых зонах; панель не торчит в мир без TLS + сильный пароль / VPN-only admin;
- секреты только в `.env` / secret store; никогда в git;
- идемпотентная выдача ключей (повтор webhook/кнопки не плодит второй аккаунт);
- rate limit на callback «Я оплатил»;
- админ-действия только по `ADMIN_IDS`;
- бэкапы БД бота и панели по расписанию;
- healthchecks + алерты в Telegram при падении polling/webhook и панели;
- Cloudflare Security Audit — перед продом и после интеграции панели.

Операционка / право (кратко, проверить с юристом):

- формулировки без «обход блокировок»;
- оферта + политика ПДн в боте;
- статус для приёма денег (часто ИП, не «голый» НПД для автосервиса);
- при приёме карт/СБП через эквайринг — касса/54-ФЗ по вашей схеме;
- серверы нод обычно вне РФ; учёт трансграничной передачи ПДн при хранении telegram_id и т.п.

---

## 2. Целевой вид продукта (Definition of Done)

Продукт «заливать на сервер и юзать», когда:

1. Бот в Docker Compose: bot + Postgres + (опц.) Redis.
2. VPN-панель установлена, inbound VLESS+REALITY (или выбранный протокол) работает.
3. После подтверждения оплаты бот **сам** создаёт пользователя в панели и шлёт subscription URL.
4. Пользователь видит «Мои заказы», срок, ссылку; может купить продление.
5. Админ: очередь, reject, stats, broadcast (минимум), ручной re-provision.
6. CI: pytest + lint на каждый PR.
7. Бэкапы, мониторинг, runbook инцидентов.
8. Пройдены: unit/flow тесты, ручной smoke на стейдже, security-audit, parallel-code-review.

---

## 3. Неограниченный план шагов

### Фаза 0 — Решение и подготовка (вы + юр/инфра)

1. Зафиксировать юрисдикцию серверов (панель / ноды / БД).
2. Выбрать панель: **Marzban** или **Remnawave** (записать в issue/ADR).
3. Выбрать протокол клиента по умолчанию: VLESS+REALITY (типичный 2026 default).
4. Решить модель оплаты v1: **остаёмся на ручном QR** до стабильной автовыдачи.
5. Завести `@BotFather` бота, получить token; записать admin telegram id.
6. Подготовить 1–2 VPS (бот+панель можно на одном только для MVP; лучше разнести).
7. Купить/указать домен для subscription page / TLS (если нужен HTTPS sub).
8. Набросать тексты оферты и политики ПДн (хотя бы черновик).
9. Открыть канал/чат поддержки (`SUPPORT_CONTACT`).
10. Согласовать тарифы и цены (уже есть seed 199/499/899 — подтвердить).

### Фаза 1 — Инженерный фундамент репо

11. ~~Оставить скиллы из `.agents/skills/`~~ — сделано.
12. Перевести зависимости на `uv`/`pyproject.toml` — опционально, позже.
13. ~~Ruff в CI~~ — сделано (`ruff.toml` + workflow). Pre-commit/gitleaks — следующий мини-шаг.
14. ~~Alembic~~ — сделано (`alembic/versions/20261024_0001_initial_schema.py`).
15. ~~Postgres в docker-compose~~ — сделано (`db` + `migrate` + `bot`).
16. Settings: `DATABASE_URL` / `AUTO_CREATE_SQLITE` готовы; `PANEL_*` — в фазе 3.
17. ~~GitHub Actions~~ — сделано (`.github/workflows/ci.yml`: ruff, pytest, docker build).
18. ~~Dockerfile + compose~~ — сделано; см. `docs/DEPLOY.md`.
19. Health endpoint или периодический self-ping админам «бот жив».
20. Структурированные логи (JSON) + request/update id.

### Фаза 2 — Железо VPN (панель)

21–30. Инструкция для вашего VPS: **`docs/MARZBAN.md`** (установка, REALITY, API, бэкап, security).  
Выполняется на сервере вручную — в репозитории код панели не ставится.

### Фаза 3 — Клиент панели в боте

31. ~~`bot/services/panel/` + `PanelClient`~~  
32. ~~Адаптер Marzban (`MarzbanClient`)~~  
33. create/extend через `ensure_subscription`; disable/usage — позже  
34. ~~username `tg<telegram_id>`~~  
35. ~~Retries на 5xx/transport в MarzbanClient~~ (circuit breaker — позже)  
36. ~~Тесты httpx MockTransport~~  
37. Staging smoke — после установки панели по `docs/MARZBAN.md`  
38. ~~Логи предупреждений при `PanelError`~~

### Фаза 4 — Автовыдача вместо ручной ссылки

39. ~~Админ «Подтвердить» → provision + send URL (если `PANEL_ENABLED=true`)~~  
40. Выдача по-прежнему только после админ-подтверждения (не после «Я оплатил»)  
41. ~~Готово для Marzban~~  
42. При ошибке панели заявка остаётся `pending_review` + кнопка «Вставить ссылку вручную»  
43. ~~`panel_username`, `expires_at`, `access_link`=subscription_url~~  
44. ~~Срок в выдаче и «Мои заказы»; кнопка «Обновить ссылку»~~  
45. ~~Повторная покупка продлевает expire~~  
46. ~~Тесты provision_and_fulfill~~  
47. Ручной smoke на вашей панели

### Фаза 5 — UX продукта

48. ~~Онбординг: /help + тексты клиентов iOS/Android/Windows~~  
49. ~~Кнопки «Инструкция» / FAQ, команды /help /faq~~  
50. ~~Напоминание за N дней (`REMINDER_DAYS_BEFORE`, фоновый loop)~~  
51. ~~«Подписка истекла» + кнопка «Продлить» / `/start renew`~~  
52. Рефералка v0 (опционально): бонусные дни, антифрод позже.  
53. Промокоды v0 (опционально).  
54. Принудительная подписка на канал (опционально, осторожно с UX).  
55. Локализация: пока только RU.  
56. ~~Антиспам: `ORDER_COOLDOWN_SECONDS` / `PAID_COOLDOWN_SECONDS`~~

### Фаза 6 — Админка оператора

57. ~~`/admin` stats: новые, pending, paid/day, active subs, panel errors~~  
58. ~~Поиск по telegram id / payment code / @username~~  
59. ~~Disable пользователя в Marzban из поиска~~  
60. ~~Broadcast с `BROADCAST_DELAY_SECONDS` + RetryAfter~~  
61. ~~Экспорт CSV (`EXPORT_DAYS`)~~  
62. ~~`admin_audit_logs`~~  
63. ~~Режим техработ (`runtime_state.maintenance`)~~

### Фаза 7 — Платежи v2 (когда ручной QR надоест)

64. ~~Шлюз v1: **Telegram Stars** (XTR); YooKassa/Platega — позже~~  
65. ~~События через polling: `pre_checkout_query` + `successful_payment` (отдельный HTTPS webhook не нужен для Stars)~~  
66. ~~Сверка currency/amount/order payload; идемпотентность по `telegram_payment_charge_id`~~  
67. ~~Авто-`fulfill` после Stars (если `PANEL_ENABLED`); иначе очередь админу~~  
68. ~~QR/перевод остаётся fallback (`STARS_ENABLED=true` → выбор способа)~~  
69. Чеки/54-ФЗ — по схеме юриста (для Stars отдельная модель TG).  
70. ~~Тесты: replay charge_id, wrong amount~~

### Фаза 8 — Надёжность «без сбоев»

71. ~~Postgres: only forward + `scripts/backup_postgres.sh` / restore + `docs/BACKUP.md`~~  
72. ~~Docker `unless-stopped` + heartbeat file healthcheck + опц. admin ping~~  
73. Лимиты устройств — ops/панель (`docs/MARZBAN.md` §8); HWID Remnawave — позже.  
74. Мультинода — ops когда вырастем (`docs/MARZBAN.md` §8).  
75. ~~Нагрузочный smoke: 100 параллельных `create_order`~~  
76. ~~Chaos панели задокументирован + деградация уже в коде~~  
77. ~~Опциональный Sentry (`SENTRY_DSN`) + JSON logs (`LOG_JSON`)~~  
78. ~~`docs/RUNBOOK.md`~~  
79. Полный `security-audit` — перед публичным запуском (скилл).  
80. `parallel-code-review` — на релизной ветке перед merge в `main`.

### Фаза 9 — Деплой «осталось залить»

81. Один `docker compose -f compose.prod.yml up -d` на VPS бота.
82. `.env.prod` только на сервере (не в git).
83. Systemd или restart policy `unless-stopped`.
84. TLS (Caddy/Nginx) если есть webhook/sub domain.
85. Firewall: наружу только 443/нужные порты Xray; SSH ключом.
86. Отдельный deploy user, без root для приложения.
87. Документ `docs/DEPLOY.md`: 15 команд от нуля до живого бота.
88. Чеклист go-live (ниже) — все пункты зелёные.
89. Мягкий запуск: 5–10 друзей, сбор багов 48 часов.
90. Публичный запуск.

### Фаза 10 — После запуска (чтобы «великолепно» держалось)

91. Еженедельный отчёт: MRR/кол-во active, churn, panel errors.
92. Патчи панели и Xray по расписанию (staging → prod).
93. Ротация секретов раз в квартал.
94. Пересмотр тарифов и capacity нод.
95. Бэклог фич только через issues; крупные — через `dag-task-runner`.

---

## 4. Go-live checklist

- [ ] Бот отвечает на `/start` с продакшен-токеном  
- [ ] Админ получает заявку после «Я оплатил»  
- [ ] Confirm создаёт юзера в панели и шлёт рабочую sub-ссылку  
- [ ] Клиент реально ходит в интернет через ноду  
- [ ] Reject не выдаёт доступ  
- [ ] Повторное нажатие paid/fulfill безопасно  
- [ ] Бэкап восстановлен хотя бы один раз на тестовой машине  
- [ ] Секреты не в git (`gitleaks` clean)  
- [ ] pytest зелёный в CI  
- [ ] security-audit: нет открытых Critical/High без решения  

---

## 5. Порядок работ агенту в Cursor (как звать)

1. Обычные фичи: «сделай … с тестами» → `vpn-bot-playbook` + `writing-tests` + `grinding-until-pass`.  
2. Крупный кусок (панель-клиент, миграция Postgres): «разбей в DAG, models `.cursor/models-vpn.json`».  
3. Перед мержем: `parallel-code-review`.  
4. Перед продом: `security-audit`.

Подробнее: `docs/SKILLS_HOWTO.md`.

---

## 6. Что сознательно не делаем в v1

- Полный клон Bedolaga/AltShop с Mini App и партнёркой.
- Свой Xray без панели.
- Автовыдача **до** подтверждения оплаты.
- Публичный админ-UI панели без TLS и без ограничений доступа.
