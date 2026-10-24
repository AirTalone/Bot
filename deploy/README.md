# Ops artifacts (фаза 9)

| Файл | Зачем |
| --- | --- |
| `env.prod.example` | Шаблон секретов → копировать в `/opt/vpn-bot/.env` |
| `vpnbot.service` | systemd: поднять compose после reboot |
| `ufw-setup.sh` | Минимальный firewall на VPS бота |
| `Caddyfile.example` | Опциональный TLS, если появится webhook/домен |

Полная инструкция: `docs/DEPLOY.md`. Чеклист: `docs/GO_LIVE.md`.
