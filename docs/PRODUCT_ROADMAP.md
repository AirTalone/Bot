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
10. Деплой-кит: compose.prod, systemd, ufw, GO_LIVE;
11. Операционка: `/report`, `docs/OPS.md`;
12. pytest на статусы и e2e-флоу без Telegram.

**Статус роадмапа:** фазы 0–10 закрыты в репозитории. На VPS остаётся выполнить `docs/DEPLOY.md` + `docs/GO_LIVE.md`.

---

## 1. Карта рынка (что есть сейчас)

### 1.1. Панели (ядро VPN)

| Панель | Сигнал | Когда брать |
| --- | --- | --- |
| **3x-ui** ([MHSanaei/3x-ui](https://github.com/MHSanaei/3x-ui)) | Быстрый старт, один сервер | Личная нода / MVP на 1 VPS |
| **Marzban** ([Gozargah/Marzban](https://github.com/Gozargah/Marzban)) | REST API, multi-node, subscription link | 2–10 нод, API к своему боту |
| **Remnawave** ([remnawave/panel](https://github.com/remnawave/panel)) | Postgres, вебхуки, HWID | Сервис на вырост |

**Выбор этого проекта:** Marzban (`docs/MARZBAN.md`).

### 1.2. Оплата

1. Ручной QR/СБП + код — старт.  
2. Telegram Stars — в коде (`STARS_ENABLED`).  
3. Эквайринг (YooKassa и т.п.) — следующий крупный бэклог через issues/`dag-task-runner`.

---

## 2. Definition of Done

1. Бот в Docker Compose: bot + Postgres.  
2. Панель выдаёт рабочий subscription URL.  
3. После подтверждения (или Stars) бот выдаёт доступ.  
4. «Мои заказы», срок, продление.  
5. Админ: очередь, reject, stats, broadcast, report.  
6. CI: pytest + lint.  
7. Бэкапы, мониторинг, runbook.  
8. Go-live чеклист зелёный.

---

## 3. Фазы (архив статусов)

### Фаза 0 — Решение и подготовка

1–10. Юрисдикция, панель, протокол, QR v1, BotFather, VPS, домен, оферта, поддержка, тарифы — **оператор**.

### Фаза 1 — Фундамент репо

11–20. ~~скиллы, Ruff/CI, Alembic, Postgres, Docker~~ · health/JSON logs — в фазе 8.

### Фаза 2 — Железо VPN

21–30. ~~`docs/MARZBAN.md`~~ (на VPS вручную).

### Фаза 3 — Клиент панели

31–38. ~~Marzban client, retries, тесты~~.

### Фаза 4 — Автовыдача

39–47. ~~confirm → provision, fallback, extend~~.

### Фаза 5 — UX

48–56. ~~help/FAQ, reminders, antispam~~ · рефералка/промо — опциональный бэклог.

### Фаза 6 — Админка

57–63. ~~stats, search, ban, broadcast, CSV, audit, maintenance~~.

### Фаза 7 — Платежи v2

64–70. ~~Stars + QR fallback, idempotency~~ · YooKassa/54-ФЗ — бэклог/юрист.

### Фаза 8 — Надёжность

71–80. ~~бэкапы, heartbeat, Sentry, runbook, load smoke~~ · полный security-audit / code-review — перед публичным запуском.

### Фаза 9 — Деплой

81–90. ~~compose.prod, systemd, ufw, DEPLOY 15 команд, GO_LIVE~~ · заливка на VPS — оператор.

### Фаза 10 — После запуска

91. ~~Еженедельный отчёт: `/report`, кнопка в `/admin`, `bot.ops_report` CLI~~  
92. ~~Патчи панели/Xray — календарь в `docs/OPS.md`~~  
93. ~~Ротация секретов — чеклист в `docs/OPS.md`~~  
94. ~~Тарифы и capacity — `docs/OPS.md`~~  
95. ~~Бэклог через issues / `dag-task-runner` — `docs/OPS.md` + `docs/SKILLS_HOWTO.md`~~

---

## 4. Go-live checklist

Актуальная версия: **`docs/GO_LIVE.md`**.

---

## 5. Порядок работ агенту в Cursor

1. Фичи: `vpn-bot-playbook` + `writing-tests` + `grinding-until-pass`.  
2. Крупное: `dag-task-runner`.  
3. Перед мержем: `parallel-code-review`.  
4. Перед продом: `security-audit`.

Подробнее: `docs/SKILLS_HOWTO.md`.

---

## 6. Что сознательно не делаем в v1

- Полный клон Bedolaga/AltShop с Mini App и партнёркой.
- Свой Xray без панели.
- Автовыдача **до** подтверждения оплаты (кроме verified Stars).
- Публичный админ-UI панели без TLS и без ограничений доступа.
