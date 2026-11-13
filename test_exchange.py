"""Тесты статусов, сервиса заявок и mock-проверки чека."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from exchange.config import Settings
from exchange.db import Database
from exchange.models import Requisites
from exchange.receipt.mock import MockReceiptChecker
from exchange.services import OrderError, OrderService
from exchange.statuses import OrderStatus, can_transition


def _settings(**overrides) -> Settings:
    base = dict(
        bot_token="test",
        database_path=Path(":memory:"),
        admin_ids=frozenset({1}),
        support_ids=frozenset({2}),
        staff_chat_id=None,
        usdt_rate_rub=100.0,
        spread_percent=0.0,
        min_amount_rub=1000.0,
        max_amount_rub=100000.0,
        payment_ttl_minutes=20,
        receipt_provider="mock",
        receipt_api_url="",
        receipt_api_key="",
        receipt_api_timeout_sec=5.0,
        receipt_fail_open_to_support=True,
        rate_mode="static",
        rate_formula="spread",
        rate_refresh_sec=60,
        rate_timeout_sec=5.0,
        cryptocards_api_url="https://cryptocards.ws/api/account",
        cryptocards_authorization="",
        cryptocards_token="",
        cryptocards_ukey="",
        cryptocards_cookie="",
        cryptocards_rate_field="rate",
        cc_edge_percent=2.0,
        markup_rub_default=1.0,
        amount_tier_30k=30_000.0,
        amount_tier_40k=40_000.0,
        amount_discount_30k=0.2,
        amount_discount_40k=0.3,
        min_margin_percent=1.0,
        min_margin_percent_40k=0.5,
        cc_rate_source="bybit_sber20",
        bybit_payment_id="585",
        bybit_side="1",
        bybit_ad_index=20,
        bybit_amount="",
    )
    base.update(overrides)
    return Settings(**base)


class StatusTests(unittest.TestCase):
    def test_happy_path_transitions(self) -> None:
        path = [
            OrderStatus.AWAITING_REQUISITES,
            OrderStatus.AWAITING_PAYMENT,
            OrderStatus.CHECKING_RECEIPT,
            OrderStatus.AWAITING_SUPPORT_REVIEW,
            OrderStatus.AWAITING_PAYOUT,
            OrderStatus.COMPLETED,
        ]
        for a, b in zip(path, path[1:]):
            self.assertTrue(can_transition(a, b), f"{a} -> {b}")

    def test_reject_then_reupload(self) -> None:
        self.assertTrue(
            can_transition(OrderStatus.CHECKING_RECEIPT, OrderStatus.RECEIPT_REJECTED)
        )
        self.assertTrue(
            can_transition(OrderStatus.RECEIPT_REJECTED, OrderStatus.CHECKING_RECEIPT)
        )


class OrderServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "t.db"
        self.settings = _settings(database_path=db_path)
        self.db = Database(db_path)
        await self.db.connect()
        self.orders = OrderService(
            db=self.db,
            settings=self.settings,
            receipt_checker=MockReceiptChecker(),
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def test_full_flow(self) -> None:
        order = await self.orders.create_order(
            client_tg_id=10,
            client_username="client",
            amount_rub=5000,
            usdt_address="TXxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        )
        self.assertEqual(order.status, OrderStatus.AWAITING_REQUISITES)
        # static fallback: USDT_RATE_RUB + markup (100 + 1)
        self.assertAlmostEqual(order.rate, 101.0)
        self.assertAlmostEqual(order.amount_usdt, 49.5)  # 49.50495 → до десятых

        order = await self.orders.assign_requisites(
            order,
            support_tg_id=2,
            requisites=Requisites(
                bank="Сбер",
                detail="+79001234567",
                holder="Иван И.",
            ),
        )
        self.assertEqual(order.status, OrderStatus.AWAITING_PAYMENT)
        self.assertIsNotNone(order.payment_deadline_at)

        order, result = await self.orders.submit_receipt(
            order,
            file_id="file",
            file_unique_id="uniq",
            file_bytes=b"%PDF ok",
            filename="receipt.pdf",
            mime_type="application/pdf",
        )
        self.assertTrue(result.ok)
        self.assertEqual(order.status, OrderStatus.AWAITING_SUPPORT_REVIEW)

        order = await self.orders.support_approve(order, support_tg_id=2)
        self.assertEqual(order.status, OrderStatus.AWAITING_PAYOUT)

        order = await self.orders.admin_complete_payout(
            order, admin_tg_id=1, txid="0xdeadbeefcafebabe"
        )
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertEqual(order.payout_txid, "0xdeadbeefcafebabe")

    async def test_receipt_fail(self) -> None:
        order = await self.orders.create_order(
            client_tg_id=11,
            client_username=None,
            amount_rub=2000,
            usdt_address="TXyyyyyyyyyyyyyyyyyyyyyyyyyyyyy",
        )
        order = await self.orders.assign_requisites(
            order,
            support_tg_id=2,
            requisites=Requisites(bank="Тинькофф", detail="2200..."),
        )
        order, result = await self.orders.submit_receipt(
            order,
            file_id="f",
            file_unique_id="u",
            file_bytes=b"x",
            filename="fail-receipt.pdf",
            mime_type="application/pdf",
        )
        self.assertFalse(result.ok)
        self.assertEqual(order.status, OrderStatus.RECEIPT_REJECTED)

        # Саппорт может одобрить вручную
        order = await self.orders.support_approve(
            order, support_tg_id=2, note="Вижу оплату в ЛК"
        )
        self.assertEqual(order.status, OrderStatus.AWAITING_PAYOUT)

    async def test_one_active_order(self) -> None:
        await self.orders.create_order(
            client_tg_id=12,
            client_username=None,
            amount_rub=3000,
            usdt_address="TXzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        )
        with self.assertRaises(OrderError):
            await self.orders.create_order(
                client_tg_id=12,
                client_username=None,
                amount_rub=3000,
                usdt_address="TXzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
            )

    async def test_optional_wallet_later(self) -> None:
        order = await self.orders.create_order(
            client_tg_id=13,
            client_username=None,
            amount_rub=4000,
            usdt_address="",
        )
        self.assertFalse(order.has_usdt_address)
        order = await self.orders.assign_requisites(
            order,
            support_tg_id=2,
            requisites=Requisites(bank="Сбер", detail="+79001112233"),
        )
        order, _ = await self.orders.submit_receipt(
            order,
            file_id="f",
            file_unique_id="u",
            file_bytes=b"ok",
            filename="ok.pdf",
            mime_type="application/pdf",
        )
        order = await self.orders.support_approve(order, support_tg_id=2)
        with self.assertRaises(OrderError):
            await self.orders.admin_complete_payout(
                order, admin_tg_id=1, txid="0xdeadbeefcafebabe"
            )
        order = await self.orders.set_usdt_address(
            order, usdt_address="TXaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        self.assertTrue(order.has_usdt_address)
        order = await self.orders.admin_complete_payout(
            order, admin_tg_id=1, txid="0xdeadbeefcafebabe"
        )
        self.assertEqual(order.status, OrderStatus.COMPLETED)


class RateCombineTests(unittest.TestCase):
    def test_max_avg_fallback(self) -> None:
        from exchange.rates.service import combine_rates

        value, formula = combine_rates(
            rapira=80.0, cryptocards=86.96, formula="max", fallback=90.0
        )
        self.assertEqual(formula, "max")
        self.assertAlmostEqual(value, 86.96)

        value, formula = combine_rates(
            rapira=80.0, cryptocards=86.96, formula="avg", fallback=90.0
        )
        self.assertEqual(formula, "avg")
        self.assertAlmostEqual(value, (80.0 + 86.96) / 2)

        value, formula = combine_rates(
            rapira=None, cryptocards=None, formula="max", fallback=90.0
        )
        self.assertEqual(formula, "fallback")
        self.assertAlmostEqual(value, 90.0)


class ClientQuoteTests(unittest.TestCase):
    def test_rapira_plus_one(self) -> None:
        from exchange.rates.pricing import compute_client_quote

        q = compute_client_quote(
            amount_rub=15_000,
            rapira=79.80,
            cryptocards=81.50,
            fallback_rate=90.0,
        )
        self.assertAlmostEqual(q.suggested_rate, 80.8)
        self.assertAlmostEqual(q.effective_cost or 0.0, 81.50 * 0.98)
        self.assertTrue(q.margin_ok)

    def test_amount_discounts(self) -> None:
        from exchange.rates.pricing import compute_client_quote

        q30 = compute_client_quote(
            amount_rub=35_000,
            rapira=80.0,
            cryptocards=81.0,
            fallback_rate=90.0,
        )
        self.assertAlmostEqual(q30.suggested_rate, 80.8)  # 81 − 0.2
        self.assertAlmostEqual(q30.amount_discount_rub, 0.2)

        q40 = compute_client_quote(
            amount_rub=50_000,
            rapira=80.0,
            cryptocards=81.0,
            fallback_rate=90.0,
        )
        self.assertAlmostEqual(q40.suggested_rate, 80.7)  # 81 − 0.3
        self.assertAlmostEqual(q40.min_margin_percent, 0.5)

    def test_reject_wide_gap_margin(self) -> None:
        """Rapira 78 / CC 83 → Rapira+1 = 79, маржа к CC×0.98 отрицательная."""
        from exchange.rates.pricing import compute_client_quote

        q = compute_client_quote(
            amount_rub=10_000,
            rapira=78.0,
            cryptocards=83.0,
            fallback_rate=90.0,
        )
        self.assertAlmostEqual(q.suggested_rate, 79.0)
        self.assertFalse(q.margin_ok)
        self.assertLess(q.margin_percent or 0.0, 0.0)


class RateSampleTests(unittest.IsolatedAsyncioTestCase):
    async def test_day_average(self) -> None:
        from exchange.rates.samples import RateSampleStore

        tmp = tempfile.TemporaryDirectory()
        store = RateSampleStore(Path(tmp.name) / "samples.db")
        await store.connect()
        try:
            await store.add_sample(source="bybit_sber20", price=86.0)
            await store.add_sample(source="bybit_sber20", price=88.0)
            avg, count = await store.day_average("bybit_sber20")
            self.assertEqual(count, 2)
            self.assertAlmostEqual(avg or 0.0, 87.0)
        finally:
            await store.close()
            tmp.cleanup()


class MockReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_mock_pass_fail(self) -> None:
        checker = MockReceiptChecker()
        ok = await checker.check(
            file_bytes=b"ok",
            filename="a.pdf",
            mime_type="application/pdf",
            expected_amount=1000,
            user_id="1",
            order_public_id="EX-1",
        )
        self.assertTrue(ok.ok)
        bad = await checker.check(
            file_bytes=b"FAIL_RECEIPT",
            filename="x.pdf",
            mime_type="application/pdf",
            expected_amount=1000,
            user_id="1",
            order_public_id="EX-1",
        )
        self.assertFalse(bad.ok)


class UsdtRoundingTests(unittest.TestCase):
    def test_round_usdt_amount(self) -> None:
        from exchange.client_card import fmt_usdt
        from exchange.rates.pricing import round_usdt_amount

        self.assertAlmostEqual(round_usdt_amount(229.2789), 229.3)
        self.assertAlmostEqual(round_usdt_amount(286.5986), 286.6)
        self.assertAlmostEqual(round_usdt_amount(229.2149), 229.2)  # теряет 0.015 — ок
        self.assertAlmostEqual(round_usdt_amount(229.2449), 229.24)  # теряет бы 0.045
        self.assertEqual(fmt_usdt(229.2789), "229.3")
        self.assertEqual(fmt_usdt(229.2449), "229.24")
        self.assertEqual(fmt_usdt(229.0), "229")


class ClientCardTests(unittest.TestCase):
    def _order(self, status, **kw):
        from datetime import datetime, timezone

        from exchange.models import Order

        now = datetime(2026, 11, 13, 4, 0, tzinfo=timezone.utc)
        base = dict(
            id=1,
            public_id="EX-ZZV21I",
            client_tg_id=10,
            client_username="client",
            amount_rub=25000.0,
            amount_usdt=286.5986,
            rate=87.23,
            usdt_address="",
            status=status,
            created_at=now,
            updated_at=now,
        )
        base.update(kw)
        return Order(**base)

    def test_all_statuses_both_styles(self) -> None:
        from exchange.client_card import client_card

        for status in OrderStatus:
            for style in ("minimal", "steps"):
                text = client_card(self._order(status), style=style)
                self.assertIn("EX-ZZV21I", text)
                self.assertIn("25 000 ₽", text)
                self.assertIn("87.23", text)

    def test_payment_shows_requisites_msk_and_escapes(self) -> None:
        from datetime import datetime, timezone

        from exchange.client_card import client_card

        order = self._order(
            OrderStatus.AWAITING_PAYMENT,
            requisites_bank="Сбер",
            requisites_detail="+7900<1>",
            requisites_holder="Иван И.",
            payment_deadline_at=datetime(2026, 11, 13, 4, 20, tzinfo=timezone.utc),
        )
        text = client_card(order, style="minimal")
        self.assertIn("+7900&lt;1&gt;", text)
        self.assertIn("07:20", text)  # 04:20 UTC = 07:20 МСК
        self.assertIn("<code>25000</code>", text)

    def test_cancel_reason_hides_tech_id(self) -> None:
        from exchange.client_card import client_card

        order = self._order(
            OrderStatus.CANCELLED, cancel_reason="Отменена клиентом (by 123456)"
        )
        text = client_card(order)
        self.assertIn("Отменена клиентом", text)
        self.assertNotIn("123456", text)


class ScreenTrackerTests(unittest.TestCase):
    """«Один экран»: новый шаг пользователя удаляет прошлые сообщения бота."""

    def setUp(self) -> None:
        from exchange.screen import ScreenTracker, Step

        self.Step = Step
        self.t = ScreenTracker()

    def send(self, step, mid, *, chat=10, menu=False):
        return self.t.register_sent(
            step=step, chat_id=chat, message_id=mid, is_menu=menu
        )

    def test_new_step_replaces_previous(self) -> None:
        s1 = self.Step(chat_id=10)
        self.assertEqual(self.send(s1, 1), [])
        s2 = self.Step(chat_id=10)
        self.assertEqual(self.send(s2, 2), [1])

    def test_several_messages_in_one_step_kept_together(self) -> None:
        s1 = self.Step(chat_id=10)
        self.send(s1, 1)
        self.assertEqual(self.send(s1, 2), [])
        self.assertEqual(self.send(s1, 3), [])
        s2 = self.Step(chat_id=10)
        self.assertEqual(self.send(s2, 4), [1, 2, 3])

    def test_pressed_message_is_replaced(self) -> None:
        # Нажали кнопку на уведомлении (id 50), которое не было «шагом»
        step = self.Step(chat_id=10, pressed_message_id=50)
        self.assertEqual(self.send(step, 51), [50])

    def test_user_text_deleted_with_reply(self) -> None:
        self.send(self.Step(chat_id=10), 1)
        # Клиент написал сумму (id 2) → бот ответил → удаляются прошлый ответ и сумма
        step = self.Step(chat_id=10, user_message_id=2)
        self.assertEqual(self.send(step, 3), [1, 2])

    def test_notifications_not_tracked(self) -> None:
        # Саппорт (чат 20) выдаёт реквизиты → сообщение в чат клиента (10)
        support_step = self.Step(chat_id=20)
        self.assertEqual(self.send(support_step, 7, chat=10), [])
        # Фон (expire_loop) — шага нет
        self.assertEqual(self.send(None, 8, chat=10), [])
        # Следующий шаг клиента не удаляет уведомления
        self.assertEqual(self.send(self.Step(chat_id=10), 9), [])

    def test_menu_message_kept_until_next_menu(self) -> None:
        self.send(self.Step(chat_id=10), 1, menu=True)  # /start
        # Следующий шаг не удаляет сообщение с клавиатурой меню
        self.assertEqual(self.send(self.Step(chat_id=10), 2), [])
        # Новое меню заменяет старое меню и прошлый шаг
        self.assertEqual(
            sorted(self.send(self.Step(chat_id=10), 3, menu=True)), [1, 2]
        )


class ScreenGroupTests(unittest.TestCase):
    def test_group_button_never_deletes_in_group(self) -> None:
        from exchange.screen import ScreenTracker, Step

        t = ScreenTracker()
        group, staff = -100500, 77
        # Сотрудник нажал кнопку на карточке в группе (сообщение 5)
        step = Step(chat_id=group, user_id=staff)
        # Обновлённая карточка уходит в группу — не трекается, ничего не удаляет
        self.assertEqual(t.register_sent(step=step, chat_id=group, message_id=6, is_menu=False), [])
        # Вопрос ушёл в личку сотрудника — трекается как его экран
        self.assertEqual(t.register_sent(step=step, chat_id=staff, message_id=1, is_menu=False), [])
        # Следующий шаг в личке заменяет этот вопрос
        step2 = Step(chat_id=staff, user_message_id=2)
        self.assertEqual(
            t.register_sent(step=step2, chat_id=staff, message_id=3, is_menu=False), [1, 2]
        )


class StaffPanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from exchange.staff_panel import StaffPanel

        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "t.db"
        self.settings = _settings(database_path=db_path, staff_chat_id=-100500)
        self.db = Database(db_path)
        await self.db.connect()

        self.calls: list[tuple] = []
        calls = self.calls
        counter = iter(range(1000, 2000))

        class FakeMsg:
            def __init__(self, mid):
                self.message_id = mid

        class FakeBot:
            async def send_message(self, chat_id, text, **kw):
                mid = next(counter)
                calls.append(("send", chat_id, mid, text, kw.get("reply_markup")))
                return FakeMsg(mid)

            async def edit_message_text(self, text, chat_id, message_id, **kw):
                calls.append(("edit", chat_id, message_id, text, kw.get("reply_markup")))

            async def delete_message(self, chat_id, message_id):
                calls.append(("delete", chat_id, message_id))

        self.panel = StaffPanel(FakeBot(), self.settings, self.db)
        self.orders = OrderService(
            db=self.db,
            settings=self.settings,
            receipt_checker=MockReceiptChecker(),
            on_change=self.panel.sync,
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def test_card_lifecycle(self) -> None:
        order = await self.orders.create_order(
            client_tg_id=10, client_username="c", amount_rub=5000,
            usdt_address="TXxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
        )
        # Новая заявка → карточка в группе с кнопкой «Взять»
        kind, chat, mid, text, kb = self.calls[-1]
        self.assertEqual((kind, chat), ("send", -100500))
        self.assertIn("Никто не взял", text)
        self.assertIn("нужны реквизиты", text)
        self.assertIn("Взять и выдать реквизиты", str(kb))

        # Реквизиты выданы → карточка редактируется на месте
        order = await self.orders.assign_requisites(
            order, support_tg_id=2, requisites=Requisites(bank="Сбер", detail="+7900")
        )
        self.assertEqual(self.calls[-1][:3], ("edit", -100500, mid))

        # Чек пришёл → нужна проверка: старая карточка удаляется, новая внизу
        order, _ = await self.orders.submit_receipt(
            order, file_id="f", file_unique_id="u", file_bytes=b"ok",
            filename="ok.pdf", mime_type="application/pdf",
        )
        kinds = [c[0] for c in self.calls[-2:]]
        self.assertEqual(kinds, ["delete", "send"])
        self.assertEqual(self.calls[-2][2], mid)

    async def test_take_and_owner_check(self) -> None:
        from types import SimpleNamespace

        order = await self.orders.create_order(
            client_tg_id=11, client_username=None, amount_rub=5000, usdt_address="",
        )
        support = SimpleNamespace(id=2, username="sup", full_name="Sup")
        other = SimpleNamespace(id=3, username="other", full_name="Other")
        admin = SimpleNamespace(id=1, username="adm", full_name="Adm")

        # Первое действие закрепляет заявку
        self.assertIsNone(await self.panel.ensure_owner(order, support))
        self.assertIn("Ведёт: @sup", self.calls[-1][3])
        # Другой сотрудник не может, админ — может
        self.assertIn("@sup", await self.panel.ensure_owner(order, other) or "")
        self.assertIsNone(await self.panel.ensure_owner(order, admin))
        # «Взять» вторым — владелец не меняется
        owner = await self.db.take_order(order.id, tg_id=3, name="@other")
        self.assertEqual(owner[0], 2)


class StatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_text(self) -> None:
        from exchange.stats import build_stats_text

        tmp = tempfile.TemporaryDirectory()
        db = Database(Path(tmp.name) / "s.db")
        await db.connect()
        try:
            orders = OrderService(
                db=db, settings=_settings(), receipt_checker=MockReceiptChecker()
            )
            o = await orders.create_order(
                client_tg_id=1, client_username=None, amount_rub=10000,
                usdt_address="TXxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
            )
            # Завершённая заявка с известной себестоимостью
            await db.update_fields(
                o.id, status=OrderStatus.COMPLETED,
                extra={"effective_cost": 95.0, "margin_percent": 6.3},
            )
            await db.take_order(o.id, tg_id=2, name="@sup")
            o2 = await orders.create_order(
                client_tg_id=5, client_username=None, amount_rub=3000, usdt_address="",
            )
            await orders.cancel(o2, reason="тест")

            text = await build_stats_text(db)
            self.assertIn("Сегодня", text)
            self.assertIn("Заявок: <b>2</b> · завершено 1", text)
            self.assertIn("10 000 ₽", text)
            self.assertIn("@sup — 1", text)
            self.assertIn("Прибыль", text)
        finally:
            await db.close()
            tmp.cleanup()


class ScreenMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_middleware_deletes_previous(self) -> None:
        from datetime import datetime, timezone

        from aiogram.methods import SendMessage
        from aiogram.types import Chat, Message

        from exchange.screen import (
            ScreenRequestMiddleware,
            ScreenTracker,
            Step,
            _current_step,
        )

        deleted: list[int] = []

        class FakeBot:
            async def delete_message(self, *, chat_id, message_id):
                deleted.append(message_id)

        counter = iter(range(100, 200))

        async def make_request(bot, method):
            return Message(
                message_id=next(counter),
                date=datetime.now(timezone.utc),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )

        mw = ScreenRequestMiddleware(ScreenTracker())
        bot = FakeBot()

        token = _current_step.set(Step(chat_id=10))
        await mw(make_request, bot, SendMessage(chat_id=10, text="шаг 1"))
        _current_step.reset(token)
        self.assertEqual(deleted, [])

        token = _current_step.set(Step(chat_id=10))
        await mw(make_request, bot, SendMessage(chat_id=10, text="шаг 2"))
        _current_step.reset(token)
        self.assertEqual(deleted, [100])


if __name__ == "__main__":
    unittest.main()
