from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import Message

from exchange.client_card import fmt_rub
from exchange.config import Settings
from exchange.staff_card import staff_rate_text
from exchange.staff_panel import STAFF_DEEPLINK
from exchange.keyboards import SUPPORT_BUTTON_TEXT, client_main_kb, support_contact_kb

router = Router(name="common")

def help_text(settings: Settings) -> str:
    """Экран «Поддержка»: частые вопросы + контакт оператора."""
    ttl = settings.payment_ttl_minutes
    steps = (
        "<b>Как проходит обмен</b>\n"
        "1. Нажмите «Обменять RUB → USDT» и укажите сумму.\n"
        "2. Оператор подберёт реквизиты для оплаты — обычно это несколько минут.\n"
        "3. Переведите точную сумму по реквизитам и нажмите «Я оплатил».\n"
        "4. Пришлите чек: PDF-файл или скриншот.\n"
        "5. После проверки оплаты оператор отправит USDT на ваш кошелёк."
    )
    faq = (
        "<b>Сколько ждать реквизиты?</b>\n"
        "Обычно несколько минут. Реквизиты придут в этот чат.\n\n"
        "<b>Сколько времени на оплату?</b>\n"
        f"{ttl} минут после получения реквизитов. Если не успели, "
        "создайте новую заявку.\n\n"
        "<b>Когда придут USDT?</b>\n"
        "После того как оператор подтвердит оплату. Хеш перевода "
        "придёт в этот чат.\n\n"
        "<b>Куда придут USDT?</b>\n"
        "На кошелёк USDT (сеть TRC-20), который вы укажете в заявке.\n\n"
        "<b>Можно ли отменить заявку?</b>\n"
        "Да. Пока вы не отправили чек, заявку можно отменить кнопкой "
        "«Отменить заявку»."
    )
    text = (
        "💬 <b>Помощь</b>\n\n"
        + steps
        + "\n\n<b>Частые вопросы</b>\n"
        + f"<blockquote>{faq}</blockquote>"
    )
    if settings.support_contact:
        text += (
            f"\n\nНе нашли ответ? Напишите оператору: @{settings.support_contact}. "
            "Укажите номер заявки — так мы ответим быстрее."
        )
    return text


def welcome_text(settings: Settings, user_id: int | None, rates=None) -> str:
    """Приветствие / главное меню: курс и лимиты во врезке + короткие шаги."""
    parts = ["👋 <b>Обмен RUB → USDT</b>"]

    quote_lines = []
    if rates is not None:
        quote_lines.append(
            f"Курс сейчас: <b>{rates.client_rate():.2f} ₽</b> за 1 USDT"
        )
    quote_lines.append(
        f"Сумма: от {fmt_rub(settings.min_amount_rub)} "
        f"до {fmt_rub(settings.max_amount_rub)} ₽"
    )
    parts.append("<blockquote>" + "\n".join(quote_lines) + "</blockquote>")

    parts.append(
        "Как это работает:\n"
        "1. Создаёте заявку\n"
        "2. Получаете реквизиты и оплачиваете\n"
        "3. Присылаете чек\n"
        "4. Получаете USDT на кошелёк"
    )
    parts.append("Нажмите «Обменять RUB → USDT», чтобы начать.")

    # Роль видят только сотрудники
    if user_id is not None and settings.is_admin(user_id):
        parts.append("<i>Ваша роль: админ</i>")
    elif user_id is not None and settings.is_support(user_id):
        parts.append("<i>Ваша роль: саппорт</i>")
    return "\n\n".join(parts)


@router.message(CommandStart(deep_link=True, magic=F.args == STAFF_DEEPLINK))
async def staff_deeplink(message: Message) -> None:
    """
    Сотрудник перешёл из рабочей группы в личку (кнопка → ссылка на бота).
    Вопрос (банк, причина, TxID…) уже ждёт в чате — меню не показываем,
    ввод не сбрасываем, служебный /start просто убираем.
    """
    try:
        await message.delete()
    except Exception:
        pass


@router.message(CommandStart())
@router.message(Command("menu"))
@router.message(F.text == "Меню")
async def cmd_start(message: Message, settings: Settings, rates) -> None:
    user_id = message.from_user.id if message.from_user else None
    await message.answer(
        welcome_text(settings, user_id, rates),
        reply_markup=client_main_kb(),
        parse_mode="HTML",
    )


@router.message(Command("help"))
@router.message(F.text == SUPPORT_BUTTON_TEXT)
@router.message(F.text == "Помощь")  # старая кнопка у тех, у кого не обновилось меню
async def cmd_help(message: Message, settings: Settings) -> None:
    await message.answer(
        help_text(settings),
        parse_mode="HTML",
        reply_markup=support_contact_kb(settings.support_contact),
    )


@router.message(Command("rate"))
@router.message(F.text == "Курс")
async def cmd_rate(message: Message, settings: Settings, rates) -> None:
    snap = rates.snapshot()
    user_id = message.from_user.id if message.from_user else None
    staff = user_id is not None and settings.is_support(user_id)

    if staff:
        text = staff_rate_text(rates, settings)
    else:
        text = snap.client_summary_html(
            min_amount_rub=settings.min_amount_rub,
            max_amount_rub=settings.max_amount_rub,
            discount_30k=settings.amount_discount_30k,
            discount_40k=settings.amount_discount_40k,
            tier_30k=settings.amount_tier_30k,
            tier_40k=settings.amount_tier_40k,
        )

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=client_main_kb(),
    )
