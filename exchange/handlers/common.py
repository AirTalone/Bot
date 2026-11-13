from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.state import default_state
from aiogram.types import Message

from exchange.client_card import fmt_rub
from exchange.config import Settings
from exchange.keyboards import SUPPORT_BUTTON_TEXT, client_main_kb, support_contact_kb

router = Router(name="common")

def help_text(settings: Settings) -> str:
    """Экран «Поддержка»: частые вопросы + контакт оператора."""
    faq = (
        "Сколько ждать реквизиты?\n"
        "Обычно несколько минут.\n\n"
        "Сколько времени на оплату?\n"
        f"{settings.payment_ttl_minutes} минут после выдачи реквизитов.\n\n"
        "Когда придут USDT?\n"
        "После того, как оператор подтвердит оплату."
    )
    text = f"💬 <b>Помощь</b>\n\n<blockquote>{faq}</blockquote>"
    if settings.support_contact:
        text += f"\n\nНе нашли ответ? Напишите оператору: @{settings.support_contact}"
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
        formula = (settings.rate_formula or "").lower()
        if formula in {"spread", "profit", "margin"}:
            extra = (
                f"\nФормула: <b>Rapira + {settings.markup_rub_default:g}</b>"
                f" · CC edge: <b>{settings.cc_edge_percent:.2f}%</b>"
                f"\nМин. маржа: ≤40к <b>{settings.min_margin_percent:.2f}%</b>, "
                f">40к <b>{settings.min_margin_percent_40k:.2f}%</b>"
            )
        else:
            extra = f"\nСпред: <b>{settings.spread_percent:.2f}%</b>"
        text = (
            snap.summary_html()
            + extra
            + f"\nЛимиты: {settings.min_amount_rub:.0f}–{settings.max_amount_rub:.0f} ₽"
        )
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
