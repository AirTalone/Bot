from datetime import UTC, datetime
from html import escape

from bot.models import Order, OrderStatus, Tariff, User
from bot.services.admin_ops import AdminStats
from bot.services.ops_report import WeeklyOpsReport
from bot.services.payments import format_money

STATUS_LABELS: dict[str, str] = {
    OrderStatus.awaiting_payment: "ожидает оплаты",
    OrderStatus.pending_review: "на проверке",
    OrderStatus.fulfilled: "доступ выдан",
    OrderStatus.rejected: "отклонена",
    OrderStatus.cancelled: "отменена",
}


def e(value: object) -> str:
    return escape(str(value), quote=False)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def format_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d.%m.%Y %H:%M UTC")


def user_label(user: User) -> str:
    if user.username:
        return f"{user.full_name} @{user.username}"
    return user.full_name


def welcome_text(*, support_contact: str, is_admin: bool) -> str:
    lines = [
        "<b>VPN</b>",
        "",
        "Выберите тариф. Бот пришлёт QR и код платежа.",
        "Переведите сумму с этим кодом в комментарии и нажмите «Я оплатил».",
        "Ссылку доступа пришлю после проверки оплаты.",
        "",
        "Команды: /orders · /help · /faq",
    ]
    if support_contact:
        lines.extend(["", f"Поддержка: {e(support_contact)}"])
    if is_admin:
        lines.extend(["", "Вам доступна команда /admin."])
    return "\n".join(lines)


def help_text(*, support_contact: str) -> str:
    lines = [
        "<b>Как подключиться</b>",
        "",
        "1. Оплатите тариф и дождитесь ссылки подписки.",
        "2. Установите клиент (кнопка «Инструкция» или /help).",
        "3. В клиенте добавьте подписку по ссылке из бота.",
        "4. Включите профиль и проверьте интернет.",
        "",
        "<b>Клиенты</b>",
        "• iOS / macOS — Streisand или Hiddify",
        "• Android — v2rayNG или Hiddify",
        "• Windows — Hiddify или Nekoray",
        "",
        "Ссылка вида <code>https://…/sub/…</code> — это подписка, не открывайте её в браузере как сайт.",
    ]
    if support_contact:
        lines.extend(["", f"Поддержка: {e(support_contact)}"])
    return "\n".join(lines)


def faq_text(*, support_contact: str) -> str:
    lines = [
        "<b>FAQ</b>",
        "",
        "<b>Когда придёт доступ?</b>",
        "После проверки оплаты администратором. Обычно в течение дня.",
        "",
        "<b>Что писать в комментарии к переводу?</b>",
        "Код платежа вида <code>VPN-XXXXXX</code> из сообщения с QR.",
        "",
        "<b>Ссылка не работает</b>",
        "Откройте «Мои заказы» → «Обновить ссылку» (если доступна) или напишите в поддержку.",
        "",
        "<b>Как продлить?</b>",
        "Купите тот же или другой тариф заново — срок добавится к текущему.",
    ]
    if support_contact:
        lines.extend(["", f"Поддержка: {e(support_contact)}"])
    return "\n".join(lines)


def cooldown_text(seconds: int) -> str:
    return f"Подождите ещё {seconds} сек. и повторите."


def tariffs_text(tariffs: list[Tariff], *, support_contact: str, is_admin: bool) -> str:
    if not tariffs:
        return "Тарифы пока не настроены."
    return welcome_text(support_contact=support_contact, is_admin=is_admin)


def choose_payment_text(order: Order, *, stars_amount: int) -> str:
    return "\n".join(
        [
            f"<b>{e(order.tariff_title)}</b>",
            f"Код: <code>{e(order.payment_code)}</code>",
            "",
            f"Stars: {stars_amount} ⭐ — доступ сразу после оплаты.",
            f"Перевод: {e(format_money(order.price_minor))} — проверка админом.",
            "",
            "Выберите способ оплаты.",
        ]
    )


def payment_caption(order: Order, *, payment_details: str) -> str:
    details = payment_details.strip()
    if len(details) > 700:
        details = details[:699] + "…"
    return "\n".join(
        [
            f"<b>{e(order.tariff_title)}</b>",
            f"К оплате: {e(format_money(order.price_minor))}",
            "",
            "Реквизиты:",
            e(details),
            "",
            "Код платежа:",
            f"<code>{e(order.payment_code)}</code>",
            "",
            "Укажите код в комментарии к переводу и нажмите «Я оплатил».",
        ]
    )


def claimed_text(order: Order) -> str:
    return "\n".join(
        [
            f"Заявка <code>{e(order.payment_code)}</code> на проверке.",
            "",
            "Как только оплата подтвердится, пришлю ссылку доступа.",
        ]
    )


def cancelled_text(order: Order) -> str:
    return f"Заявка <code>{e(order.payment_code)}</code> отменена."


def access_granted_text(order: Order) -> str:
    lines = [
        "<b>Оплата подтверждена</b>",
        "",
        f"Тариф: {e(order.tariff_title)} ({order.duration_days} дн.)",
        f"Код: <code>{e(order.payment_code)}</code>",
    ]
    if order.expires_at is not None:
        lines.append(f"Действует до: {format_dt(order.expires_at)}")
    lines.extend(
        [
            "",
            "Ссылка подписки:",
            f"<code>{e(order.access_link)}</code>",
            "",
            "Дальше — кнопка «Инструкция» или команда /help.",
        ]
    )
    return "\n".join(lines)


def reminder_text(order: Order) -> str:
    return "\n".join(
        [
            "<b>Подписка скоро закончится</b>",
            "",
            f"Тариф: {e(order.tariff_title)}",
            f"Действует до: {format_dt(order.expires_at)}",
            "",
            "Продлите доступ заранее — срок добавится к текущему.",
        ]
    )


def expired_text(order: Order) -> str:
    return "\n".join(
        [
            "<b>Подписка истекла</b>",
            "",
            f"Тариф: {e(order.tariff_title)}",
            f"Код: <code>{e(order.payment_code)}</code>",
            "",
            "Выберите тариф, чтобы продлить доступ.",
        ]
    )


def refreshed_link_text(order: Order) -> str:
    lines = [
        "<b>Ссылка обновлена</b>",
        "",
        f"<code>{e(order.access_link)}</code>",
    ]
    if order.expires_at is not None:
        lines.extend(["", f"Действует до: {format_dt(order.expires_at)}"])
    return "\n".join(lines)


def rejected_text(order: Order, *, support_contact: str) -> str:
    lines = [
        f"Оплата по заявке <code>{e(order.payment_code)}</code> не подтверждена.",
        "",
        "Если деньги уже списались, напишите в поддержку.",
    ]
    if support_contact:
        lines.extend(["", e(support_contact)])
    return "\n".join(lines)


def _is_expired(order: Order) -> bool:
    if order.expires_at is None:
        return False
    expires = order.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    return expires <= datetime.now(UTC)


def _order_line(order: Order) -> str:
    status = status_label(order.status)
    if order.status == OrderStatus.fulfilled and _is_expired(order):
        status = "истекла"
    line = (
        f"<code>{e(order.payment_code)}</code> · {e(order.tariff_title)} · "
        f"{e(format_money(order.price_minor))} · {e(status)}"
    )
    if order.expires_at is not None and order.status == OrderStatus.fulfilled:
        line += f"\nдо {format_dt(order.expires_at)}"
    if order.status == OrderStatus.fulfilled and order.access_link and not _is_expired(order):
        line += f"\n<code>{e(order.access_link)}</code>"
    return line


def orders_text(orders: list[Order]) -> str:
    if not orders:
        return "Заказов пока нет. Выберите тариф, чтобы оформить доступ."
    lines = ["<b>Мои заказы</b>", ""]
    lines.extend(_order_line(order) for order in orders)
    return "\n".join(lines)


def admin_home_text(stats: AdminStats) -> str:
    mode = "техработы ВКЛ" if stats.maintenance else "обычный режим"
    return "\n".join(
        [
            "<b>Админка</b>",
            f"Режим: {mode}",
            "",
            f"Новые (ждут оплату): {stats.awaiting_payment}",
            f"На проверке: {stats.pending_review}",
            f"Выдано сегодня: {stats.fulfilled_today}",
            f"Активные подписки: {stats.active_subs}",
            f"Ошибки панели сегодня: {stats.panel_errors_today}",
            f"Пользователей: {stats.users_total}",
            "",
            "Очередь → подтверждение → ссылка. Поиск / рассылка / CSV / отчёт — кнопки ниже.",
            "Команда /report — недельный отчёт.",
        ]
    )


def weekly_ops_report_text(report: WeeklyOpsReport) -> str:
    return "\n".join(
        [
            f"<b>Недельный отчёт</b> ({report.window_days}д)",
            f"окно: {format_dt(report.since)} — {format_dt(report.until)}",
            "",
            f"Active: {report.active_subs}",
            f"Новые пользователи: {report.new_users}",
            f"Выдано заказов: {report.fulfilled_count}",
            f"Выручка за окно: {report.revenue_text}",
            f"Approx MRR (30д): {report.approx_mrr_text}",
            f"Истекло за окно: {report.expired_count}",
            f"Churn proxy: {report.churn_proxy_pct:.1f}%",
            f"Ошибки панели: {report.panel_errors}",
            f"Сейчас на проверке: {report.pending_review}",
            f"Оплаты Stars / QR: {report.stars_payments} / {report.qr_payments}",
            "",
            "MRR и churn — прокси по заказам бота, не бухгалтерия.",
        ]
    )


def maintenance_user_text(*, support_contact: str) -> str:
    lines = [
        "<b>Технические работы</b>",
        "",
        "Покупки временно выключены. Попробуйте позже.",
    ]
    if support_contact:
        lines.extend(["", f"Поддержка: {e(support_contact)}"])
    return "\n".join(lines)


def ask_search_text() -> str:
    return "\n".join(
        [
            "Поиск: пришлите <code>telegram id</code>, код платежа или @username.",
            "/cancel — отмена.",
        ]
    )


def search_results_text(orders: list[Order]) -> str:
    if not orders:
        return "Ничего не найдено."
    lines = ["<b>Результаты поиска</b>", ""]
    for order in orders:
        lines.append(
            f"<code>{e(order.payment_code)}</code> · {e(status_label(order.status))} · "
            f"{e(user_label(order.user))} · id <code>{order.user.telegram_id}</code>"
        )
        if order.panel_username:
            lines.append(f"панель: <code>{e(order.panel_username)}</code>")
    return "\n".join(lines)


def ask_broadcast_text() -> str:
    return "\n".join(
        [
            "Рассылка: пришлите текст сообщения (HTML как в боте).",
            "/cancel — отмена.",
        ]
    )


def confirm_broadcast_text(preview: str, recipients: int) -> str:
    short = preview if len(preview) <= 500 else preview[:499] + "…"
    return "\n".join(
        [
            f"Разослать {recipients} пользователям?",
            "",
            short,
        ]
    )


def broadcast_done_text(*, sent: int, failed: int) -> str:
    return f"Рассылка завершена. Доставлено: {sent}, ошибок: {failed}."


def ban_done_text(order: Order) -> str:
    username = order.panel_username or "—"
    return f"Пользователь панели <code>{e(username)}</code> отключён (заказ <code>{e(order.payment_code)}</code>)."


def pending_list_text(orders: list[Order], total: int) -> str:
    if not orders:
        return "Нет заявок на проверке."
    lines = ["<b>Заявки на проверке</b>", ""]
    for order in orders:
        lines.append(
            f"<code>{e(order.payment_code)}</code> · {e(order.tariff_title)} · "
            f"{e(format_money(order.price_minor))} · {e(user_label(order.user))}"
        )
    if total > len(orders):
        lines.extend(["", f"Показаны {len(orders)} из {total}."])
    return "\n".join(lines)


def admin_order_text(order: Order, *, panel_enabled: bool = False) -> str:
    method = "Stars" if order.payment_method == "stars" else "перевод / QR"
    lines = [
        f"<b>Заявка #{order.id}</b>",
        f"Статус: {e(status_label(order.status))}",
        f"Код: <code>{e(order.payment_code)}</code>",
        f"Способ: {method}",
        f"Тариф: {e(order.tariff_title)} ({order.duration_days} дн.)",
        f"Сумма: {e(format_money(order.price_minor))}",
    ]
    if order.payment_method == "stars" and order.stars_amount:
        lines.append(f"Stars: {order.stars_amount} ⭐")
    lines.extend(
        [
            f"Пользователь: {e(user_label(order.user))}",
            f"id: <code>{order.user.telegram_id}</code>",
            f"Создана: {format_dt(order.created_at)}",
        ]
    )
    if order.payment_method == "stars":
        lines.extend(["", "Оплата Stars уже подтверждена Telegram."])
    if panel_enabled:
        lines.extend(["", "Панель: Marzban включена. «Подтвердить» создаст/продлит пользователя автоматически."])
    return "\n".join(lines)


def stars_paid_pending_text(order: Order) -> str:
    return "\n".join(
        [
            f"Оплата Stars по заявке <code>{e(order.payment_code)}</code> получена.",
            "",
            "Панель выключена — админ вставит ссылку вручную. Напишу, как только доступ будет готов.",
        ]
    )


def stars_invoice_title(order: Order) -> str:
    return f"VPN · {order.tariff_title}"[:32]


def stars_invoice_description(order: Order) -> str:
    return f"Доступ на {order.duration_days} дн. Код {order.payment_code}"[:255]


def panel_failed_text(order: Order, detail: str) -> str:
    short = detail.strip()
    if len(short) > 400:
        short = short[:399] + "…"
    return "\n".join(
        [
            f"Не удалось выдать доступ по заявке <code>{e(order.payment_code)}</code> через панель.",
            e(short),
            "",
            "Заявка осталась на проверке. Нажмите «Вставить ссылку вручную» или повторите подтверждение.",
        ]
    )


def ask_link_text(order: Order) -> str:
    return "\n".join(
        [
            f"Заявка <code>{e(order.payment_code)}</code>",
            "",
            "Отправьте ссылку доступа одним сообщением.",
            "/cancel — вернуться без выдачи.",
        ]
    )


def link_sent_text(order: Order) -> str:
    return f"Ссылка по заявке <code>{e(order.payment_code)}</code> отправлена."


def link_saved_undelivered_text(order: Order) -> str:
    return (
        f"Ссылка по заявке <code>{e(order.payment_code)}</code> сохранена, "
        "но написать пользователю не удалось. Когда он откроет бота, ссылка будет в «Мои заказы»."
    )


def rejected_admin_text(order: Order) -> str:
    return f"Заявка <code>{e(order.payment_code)}</code> отклонена."
