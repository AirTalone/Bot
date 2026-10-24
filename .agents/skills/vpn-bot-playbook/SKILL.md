---
name: vpn-bot-playbook
description: >-
  Project playbook for AirTalone VPN Telegram bot (Python, aiogram 3, manual QR
  payment, admin confirmation, access link / panel provisioning). Use for any
  feature, bugfix, deploy, or security work in this repository. Routes the
  agent to the right installed skills and keeps the payment flow consistent.
---

# VPN-bot playbook (this repo)

## Product shape

- Buyer flow: tariff → QR + payment code → «Я оплатил» → admin confirm → access link.
- Stack: Python 3.11+, aiogram 3, SQLAlchemy async, SQLite now / Postgres later.
- Access is eventually provisioned from a VPN panel API (Marzban or Remnawave), not invented by the bot.

## When you change code

1. Read `docs/PRODUCT_ROADMAP.md` for the current phase and DoD.
2. Prefer small diffs. Keep order status transitions in `bot/services/orders.py`.
3. Never hardcode `BOT_TOKEN`, admin ids, panel passwords, or payment secrets.
4. After behavior changes, extend tests under `tests/` and run `python -m pytest`.
5. Use installed skills below instead of inventing process from scratch.

## Skill routing (use these)

| Situation | Skill |
| --- | --- |
| Large multi-file feature, fan-out work | `dag-task-runner` with `.cursor/models-vpn.json` |
| Telegram / aiogram handlers, FSM, keyboards | `telegram-bot` |
| New/changed tests | `writing-tests` then `grinding-until-pass` |
| Bug investigation | `systematic-debugging` |
| Everyday security / secrets / IDOR | `auditing-security` |
| Risky PR before merge | `parallel-code-review` |
| Full pre-prod audit | `security-audit` (Cloudflare) — explicit request only |
| Models / migrations / settings | `sqlalchemy-models`, `alembic-migrations`, `settings-config` |
| Lint/tooling hygiene | `code-quality` |
| Dockerfile / compose | `adding-docker` |
| GitHub Actions | `setting-up-ci` |
| Turn a repeated workflow into a skill | `building-skills-from-patterns` |

## Payment invariants

- One unpaid (`awaiting_payment`) checkout per user; creating a new one cancels only unpaid.
- `pending_review` is never cancelled by a new checkout.
- Only the buyer can press «Я оплатил» / cancel their awaiting order.
- Only admins fulfill/reject; access link must contain `://` and no spaces.
- Payment code stays in the caption even when `PAYMENT_QR_PAYLOAD` is a bank URL.

## Safe phrases for the user to invoke

- «Разбей в DAG по vpn models»
- «Допиши тесты и крути grinding-until-pass»
- «Сделай parallel-code-review по diff»
- «Полный security-audit, отчёт вне git»
