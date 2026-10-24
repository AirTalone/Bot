# Операционка после запуска (фаза 10)

Чтобы сервис «держал форму», а не только запустился один раз.

## 1. Еженедельный отчёт

В боте (админ):

- кнопка **«Недельный отчёт»** в `/admin`
- команда `/report`

Метрики (прокси, не бухгалтерский MRR):

| Поле | Смысл |
| --- | --- |
| Active | fulfilled + не истёкшие |
| Revenue 7d | сумма `price_minor` выданных за 7 дней |
| Approx MRR | сумма выданных за 30 дней |
| Churn proxy | истекшие за 7д / (active + истекшие) |
| Panel errors | `admin_audit_logs.action=panel_error` за 7д |

Cron (опционально, печать в лог на сервере):

```cron
0 9 * * 1 deploy cd /opt/vpn-bot && docker compose -f compose.prod.yml exec -T bot python -m bot.ops_report >>/var/log/vpnbot-report.log 2>&1
```

Или просто каждый понедельник жмите `/report` в Telegram.

## 2. Патчи панели и Xray

Расписание (рекомендация):

1. **Staging / тестовая нода** — читаете release notes Marzban/Xray.  
2. Смоук: создать user → sub URL → клиент онлайн.  
3. **Prod** — в окно низкой нагрузки; заранее бэкап панели (`docs/MARZBAN.md`).  
4. После патча: одна тестовая выдача из бота (`PANEL_ENABLED`).

Не обновляйте панель и бота «в один клик без бэкапа». Если API сломался — бот деградирует в ручную ссылку (`docs/RUNBOOK.md`).

## 3. Ротация секретов (раз в квартал)

Чеклист:

- [ ] Новый `BOT_TOKEN` у `@BotFather` → `.env` → `docker compose -f compose.prod.yml up -d --force-recreate bot`
- [ ] Новый `POSTGRES_PASSWORD` (или роль) + обновить `DATABASE_URL` / compose env + recreate
- [ ] Новый пароль Marzban admin / API user → `PANEL_PASSWORD`
- [ ] Проверить, что старые секреты нигде не закоммичены
- [ ] Запись в календарь: дата ротации

Не ротируйте всё одновременно в пятницу вечером без бэкапа.

## 4. Тарифы и capacity нод

Раз в месяц (или при росте active):

1. `/report` + CSV экспорт — смотрите выручку и churn proxy.  
2. Цены: таблица `tariffs` (`price_minor`, `stars_price`); seed не затирает существующие.  
3. Нода: CPU/канал/число online в панели; при упоре — вторая нода Marzban (`docs/MARZBAN.md` §8).  
4. Не поднимайте цены без предупреждения активным (рассылка из `/admin`).

## 5. Бэклог фич

- Мелкое — GitHub Issues, один issue = одна поставка.  
- Крупное (платёжный шлюз, смена панели) — скилл `dag-task-runner` + models JSON, см. `docs/SKILLS_HOWTO.md`.  
- Не тащите Mini App / партнёрку «потому что у конкурентов есть» без issue и оценки.

## 6. Календарь оператора (шпаргалка)

| Когда | Что |
| --- | --- |
| Ежедневно | бэкап Postgres (cron), взгляд на pending в `/admin` |
| Еженедельно | `/report`, разбор panel errors |
| Ежемесячно | restore drill, тарифы/capacity |
| Ежеквартально | ротация секретов, security-audit скилл |
