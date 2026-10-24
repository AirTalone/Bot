from datetime import datetime, timezone

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.methods import TelegramMethod
from aiogram.methods.base import TelegramType
from aiogram.types import CallbackQuery, Chat, Message, Update, User
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.callbacks import CheckoutAction, TariffSelect
from bot.config import Settings
from bot.handlers import admin_router, payments_router, user_router
from bot.middlewares import DbSessionMiddleware
from bot.models import OrderStatus
from bot.services.orders import get_order, list_active_tariffs, list_user_orders

BUYER_ID = 42
ADMIN_ID = 7
ACCESS_LINK = "vless://uuid@host:443?type=tcp#node"


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[TelegramType]] = []

    async def close(self) -> None:
        return None

    async def stream_content(
        self,
        url: str,
        headers: dict[str, object] | None = None,
        timeout: int = 30,
        chunk_size: int = 65536,
        raise_for_status: bool = True,
    ):
        yield b""

    async def make_request(
        self,
        bot: Bot,
        method: TelegramMethod[TelegramType],
        timeout: int | None = None,
    ) -> TelegramType:
        self.calls.append(method)
        name = type(method).__name__
        if name in {"SendMessage", "SendPhoto", "EditMessageText", "EditMessageReplyMarkup"}:
            return Message(
                message_id=len(self.calls),
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type=ChatType.PRIVATE),
                text=getattr(method, "text", None),
                caption=getattr(method, "caption", None),
            )
        if name == "AnswerCallbackQuery":
            return True
        raise AssertionError(f"unexpected telegram method {name}")


def _person(user_id: int, first_name: str, username: str | None = None) -> User:
    return User(id=user_id, is_bot=False, first_name=first_name, username=username)


def _message(user: User, text: str, update_id: int) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(timezone.utc),
            chat=Chat(id=user.id, type=ChatType.PRIVATE),
            from_user=user,
            text=text,
        ),
    )


def _callback(user: User, data: str, update_id: int) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=f"cb{update_id}",
            from_user=user,
            chat_instance="test",
            data=data,
            message=Message(
                message_id=update_id,
                date=datetime.now(timezone.utc),
                chat=Chat(id=user.id, type=ChatType.PRIVATE),
                from_user=User(id=999, is_bot=True, first_name="VPN", username="vpn_bot"),
                text="menu",
            ),
        ),
    )


def _describe(calls: list[TelegramMethod[TelegramType]]) -> str:
    lines: list[str] = []
    for call in calls:
        text = getattr(call, "text", None) or getattr(call, "caption", None) or ""
        lines.append(f"{type(call).__name__} chat={getattr(call, 'chat_id', None)} {text[:120]!r}")
    return "\n".join(lines)


async def test_qr_payment_flow(session_factory: async_sessionmaker[AsyncSession]) -> None:
    settings = Settings(
        bot_token="123456:TESTTOKEN",
        admin_ids=str(ADMIN_ID),
        payment_title="Оплата VPN",
        payment_details="СБП +7 900 000-00-00",
        payment_qr_payload="",
        support_contact="@support",
        order_cooldown_seconds=0,
        paid_cooldown_seconds=0,
    )
    dispatcher = Dispatcher(storage=MemoryStorage(), settings=settings)
    dispatcher.update.middleware(DbSessionMiddleware(session_factory))
    dispatcher.include_router(admin_router)
    dispatcher.include_router(payments_router)
    dispatcher.include_router(user_router)

    fake = FakeSession()
    bot = Bot(
        token=settings.bot_token,
        session=fake,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    buyer = _person(BUYER_ID, "Иван", "ivan")
    admin = _person(ADMIN_ID, "Админ")

    async with session_factory() as session:
        tariff = (await list_active_tariffs(session))[0]

    try:
        await dispatcher.feed_update(bot, _message(buyer, "/admin", 1))
        assert any(
            type(call).__name__ == "SendMessage" and "только администратору" in (call.text or "")
            for call in fake.calls
        ), _describe(fake.calls)

        await dispatcher.feed_update(bot, _message(buyer, "/start", 2))
        await dispatcher.feed_update(
            bot,
            _callback(buyer, TariffSelect(tariff_id=tariff.id).pack(), 3),
        )

        photo = next(call for call in fake.calls if type(call).__name__ == "SendPhoto")
        assert photo.chat_id == BUYER_ID
        assert "СБП +7 900" in photo.caption
        assert photo.photo.data.startswith(b"\x89PNG")
        paid_data = photo.reply_markup.inline_keyboard[0][0].callback_data
        checkout = CheckoutAction.unpack(paid_data)
        assert checkout.action == "paid"

        await dispatcher.feed_update(bot, _callback(buyer, paid_data, 4))

        async with session_factory() as session:
            pending = await get_order(session, checkout.order_id)
        assert pending is not None
        assert pending.status == OrderStatus.pending_review
        assert any(
            type(call).__name__ == "SendMessage"
            and call.chat_id == ADMIN_ID
            and pending.payment_code in (call.text or "")
            for call in fake.calls
        ), _describe(fake.calls)

        confirm_data = next(
            call.reply_markup.inline_keyboard[0][0].callback_data
            for call in fake.calls
            if type(call).__name__ == "SendMessage" and call.chat_id == ADMIN_ID
        )
        await dispatcher.feed_update(bot, _callback(admin, confirm_data, 5))
        await dispatcher.feed_update(bot, _message(admin, "просто текст", 6))

        async with session_factory() as session:
            still_pending = await get_order(session, checkout.order_id)
        assert still_pending is not None
        assert still_pending.status == OrderStatus.pending_review

        await dispatcher.feed_update(bot, _message(admin, ACCESS_LINK, 7))

        async with session_factory() as session:
            fulfilled = await get_order(session, checkout.order_id)
            assert fulfilled is not None
            assert fulfilled.status == OrderStatus.fulfilled
            assert fulfilled.access_link == ACCESS_LINK
            buyer_orders = await list_user_orders(session, fulfilled.user_id)
        assert buyer_orders[0].payment_code == fulfilled.payment_code
        assert any(
            type(call).__name__ == "SendMessage"
            and call.chat_id == BUYER_ID
            and ACCESS_LINK in (call.text or "")
            for call in fake.calls
        ), _describe(fake.calls)
    finally:
        await bot.session.close()
