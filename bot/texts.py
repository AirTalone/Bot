from datetime import datetime
from html import escape

from bot.models import Order, OrderStatus, Tariff, User
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
    ]
    if support_contact:
        lines.extend(["", f"Поддержка: {e(support_contact)}"])
    if is_admin:
        lines.extend(["", "Вам доступна команда /admin."])
    return "\n".join(lines)


def tariffs_text(tariffs: list[Tariff], *, support_contact: str, is_admin: bool) -> str:
    if not tariffs:
        return "Тарифы пока не настроены."
    return welcome_text(support_contact=support_contact, is_admin=is_admin)


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
    return "\n".join(
        [
            "<b>Оплата подтверждена</b>",
            "",
            f"Тариф: {e(order.tariff_title)} ({order.duration_days} дн.)",
            f"Код: <code>{e(order.payment_code)}</code>",
            "",
            "Ссылка доступа:",
            f"<code>{e(order.access_link)}</code>",
        ]
    )


def rejected_text(order: Order, *, support_contact: str) -> str:
    lines = [
        f"Оплата по заявке <code>{e(order.payment_code)}</code> не подтверждена.",
        "",
        "Если деньги уже списались, напишите в поддержку.",
    ]
    if support_contact:
        lines.extend(["", e(support_contact)])
    return "\n".join(lines)


def _order_line(order: Order) -> str:
    line = (
        f"<code>{e(order.payment_code)}</code> · {e(order.tariff_title)} · "
        f"{e(format_money(order.price_minor))} · {e(status_label(order.status))}"
    )
    if order.status == OrderStatus.fulfilled and order.access_link:
        line += f"\n<code>{e(order.access_link)}</code>"
    return line


def orders_text(orders: list[Order]) -> str:
    if not orders:
        return "Заказов пока нет. Выберите тариф, чтобы оформить доступ."
    lines = ["<b>Мои заказы</b>", ""]
    lines.extend(_order_line(order) for order in orders)
    return "\n".join(lines)


def admin_home_text(pending_count: int) -> str:
    return "\n".join(
        [
            "<b>Админка</b>",
            "",
            f"Заявок на проверке: {pending_count}",
            "",
            "Откройте заявку, подтвердите оплату и отправьте ссылку доступа.",
        ]
    )


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


def admin_order_text(order: Order) -> str:
    return "\n".join(
        [
            f"<b>Заявка #{order.id}</b>",
            f"Статус: {e(status_label(order.status))}",
            f"Код: <code>{e(order.payment_code)}</code>",
            f"Тариф: {e(order.tariff_title)} ({order.duration_days} дн.)",
            f"Сумма: {e(format_money(order.price_minor))}",
            f"Пользователь: {e(user_label(order.user))}",
            f"id: <code>{order.user.telegram_id}</code>",
            f"Создана: {format_dt(order.created_at)}",
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
