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
        support_contact="Georgina771",
        usdt_rate_rub=100.0,
        spread_percent=0.0,
        min_amount_rub=1000.0,
        max_amount_rub=100000.0,
        payment_ttl_minutes=30,
        payment_ttl_extended_minutes=60,
        receipt_provider="mock",
        receipt_api_url="",
        receipt_api_key="",
        receipt_api_timeout_sec=5.0,
        receipt_fail_open_to_support=True,
        rate_mode="static",
        rate_formula="spread",
        target_income_percent=1.25,
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
        self.assertAlmostEqual(q.effective_cost or 0.0, 81.50 / 1.02, places=3)
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


class CcFormulaTests(unittest.TestCase):
    """Курс клиенту от курса CryptoCards с вашим доходом N%."""

    def _q(self, **kw):
        from exchange.rates.pricing import compute_client_quote

        base = dict(
            amount_rub=13_000, rapira=86.23, cryptocards=88.4627,
            fallback_rate=90.0, formula="cc", income_percent=1.25,
        )
        base.update(kw)
        return compute_client_quote(**base)

    def test_income_125_gives_8781(self) -> None:
        q = self._q()
        self.assertAlmostEqual(q.suggested_rate, 87.81)
        self.assertTrue(q.formula.startswith("cc"))
        # Доход (маржа к себестоимости) ≈ заданным 1.25%
        self.assertAlmostEqual(q.margin_percent or 0, 1.25, delta=0.02)
        self.assertTrue(q.margin_ok)
        self.assertEqual(q.to_extra()["income_percent"], 1.25)

    def test_income_2_equals_cc_rate(self) -> None:
        # Как на скриншоте CC: 13 000 ₽ по 88.39 = 147.07 USDT, доход 2% целиком ваш
        q = self._q(cryptocards=13000 / 147.07, income_percent=2.0)
        self.assertAlmostEqual(q.suggested_rate, round(13000 / 147.07, 2))

    def test_amount_discount_applies(self) -> None:
        q = self._q(amount_rub=35_000)
        self.assertAlmostEqual(q.suggested_rate, 87.61)  # 87.81 − 0.2

    def test_no_cc_falls_back_to_rapira(self) -> None:
        q = self._q(cryptocards=None)
        self.assertAlmostEqual(q.suggested_rate, 87.23)  # 86.23 + 1
        self.assertTrue(q.formula.startswith("rapira"))
        self.assertIsNone(q.margin_ok)
        self.assertIsNone(q.to_extra()["income_percent"])


class ClientOrderKbTests(unittest.TestCase):
    def test_new_order_button_on_closed(self) -> None:
        from datetime import datetime, timezone

        from exchange.keyboards import client_order_kb
        from exchange.models import Order

        now = datetime.now(timezone.utc)

        def kb_data(status):
            o = Order(
                id=1, public_id="EX-1", client_tg_id=1, client_username=None,
                amount_rub=5000, amount_usdt=57.0, rate=87.8, usdt_address="",
                status=status, created_at=now, updated_at=now,
            )
            return [b.callback_data for row in client_order_kb(o).inline_keyboard for b in row]

        for status in (OrderStatus.CANCELLED, OrderStatus.EXPIRED, OrderStatus.COMPLETED):
            data = kb_data(status)
            self.assertIn("client:new", data)
            self.assertNotIn("client:status:1", data)
        active = kb_data(OrderStatus.AWAITING_PAYMENT)
        self.assertIn("client:status:1", active)
        self.assertNotIn("client:new", active)


class RequisitesPromptTests(unittest.TestCase):
    def test_bank_buttons_and_skip(self) -> None:
        from exchange.handlers.support import REQ_BANKS, _req_kb

        bank_kb = _req_kb("bank")
        texts = [b.text for row in bank_kb.inline_keyboard for b in row]
        for name in REQ_BANKS:
            self.assertIn(name, texts)
        self.assertIn("✖️ Отменить выдачу", texts)
        holder = [b.callback_data for row in _req_kb("holder").inline_keyboard for b in row]
        self.assertIn("reqholder:skip", holder)


class StaffRateTextTests(unittest.TestCase):
    def test_staff_rate_text(self) -> None:
        from exchange.rates.pricing import compute_client_quote
        from exchange.rates.service import RateService, RateSnapshot, utcnow
        from exchange.staff_card import staff_rate_text

        s = _settings(rate_mode="auto", rate_formula="cc")
        r = RateService(s)
        q = compute_client_quote(
            amount_rub=0, rapira=86.23, cryptocards=88.48, fallback_rate=90,
            formula="cc", income_percent=1.25,
        )
        r._snapshot = RateSnapshot(
            rapira=86.23, cryptocards=88.48, bybit_nth=None, base=88.48,
            client=q.suggested_rate, formula=q.formula, mode="auto",
            updated_at=utcnow(), effective_cost=q.effective_cost,
            expected_margin_percent=q.margin_percent,
        )
        text = staff_rate_text(r, s)
        self.assertIn("CC: <b>88.48</b>", text)
        self.assertIn("Ваш доход: <b>1.25%</b>", text)
        self.assertIn("Курс клиенту: <b>87.83 ₽</b>", text)
        self.assertIn("свыше 30к → 87.63", text)


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


class SupportHelpTests(unittest.TestCase):
    def test_help_text_and_button(self) -> None:
        from exchange.handlers.common import help_text
        from exchange.keyboards import support_contact_kb

        s = _settings(payment_ttl_minutes=30, payment_ttl_extended_minutes=60)
        text = help_text(s)
        self.assertIn("30 минут", text)
        self.assertIn("до 60 минут", text)
        self.assertIn("@Georgina771", text)
        kb = support_contact_kb(s.support_contact)
        self.assertEqual(kb.inline_keyboard[0][0].url, "https://t.me/Georgina771")
        self.assertIsNone(support_contact_kb(""))


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


class PaymentDeadlineTests(unittest.IsolatedAsyncioTestCase):
    """30 минут на оплату; саппорт продлевает до 60 (клиент говорит с банком)."""

    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "t.db"
        self.db = Database(db_path)
        await self.db.connect()
        self.orders = OrderService(
            db=self.db,
            settings=_settings(database_path=db_path),
            receipt_checker=MockReceiptChecker(),
        )
        order = await self.orders.create_order(
            client_tg_id=20, client_username=None, amount_rub=5000, usdt_address="",
        )
        self.order = await self.orders.assign_requisites(
            order, support_tg_id=2, requisites=Requisites(bank="Сбер", detail="+7900")
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    def _minutes(self, order) -> float:
        return (order.payment_deadline_at - order.requisites_at).total_seconds() / 60

    async def test_default_30_then_extend_to_60_once(self) -> None:
        self.assertAlmostEqual(self._minutes(self.order), 30, delta=0.1)
        order = await self.orders.extend_payment(self.order, support_tg_id=2)
        self.assertAlmostEqual(self._minutes(order), 60, delta=0.1)
        self.assertTrue(order.extra.get("deadline_extended"))
        with self.assertRaises(OrderError):
            await self.orders.extend_payment(order, support_tg_id=2)

    async def test_extend_only_while_awaiting_payment(self) -> None:
        order = await self.orders.cancel(self.order, reason="тест")
        with self.assertRaises(OrderError):
            await self.orders.extend_payment(order, support_tg_id=2)

    async def test_repay_gives_fresh_deadline(self) -> None:
        from datetime import datetime, timezone

        order, _ = await self.orders.submit_receipt(
            self.order, file_id="f", file_unique_id="u", file_bytes=b"ok",
            filename="ok.pdf", mime_type="application/pdf",
        )
        order = await self.orders.support_request_new_payment(order, support_tg_id=2)
        left = (order.payment_deadline_at - datetime.now(timezone.utc)).total_seconds() / 60
        self.assertAlmostEqual(left, 30, delta=0.2)


class PdfVideoTrustedTests(unittest.IsolatedAsyncioTestCase):
    """Чек только PDF; видео перевода; доверенным клиентам видео не нужно."""

    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "t.db"
        self.db = Database(db_path)
        await self.db.connect()
        self.orders = OrderService(
            db=self.db,
            settings=_settings(database_path=db_path),
            receipt_checker=MockReceiptChecker(),
        )

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def _paid_order(self, client_id: int):
        order = await self.orders.create_order(
            client_tg_id=client_id, client_username="c", amount_rub=5000, usdt_address="",
        )
        return await self.orders.assign_requisites(
            order, support_tg_id=2, requisites=Requisites(bank="Сбер", detail="+7900")
        )

    async def test_new_client_needs_video_and_it_is_stored(self) -> None:
        from exchange.client_card import client_card
        from exchange.keyboards import support_order_kb
        from exchange.staff_card import staff_card

        order = await self._paid_order(30)
        self.assertTrue(order.extra["video_required"])
        self.assertIn("запись экрана", client_card(order))
        self.assertNotIn("скриншот", client_card(order))
        order, _ = await self.orders.submit_receipt(
            order, file_id="pdf", file_unique_id="u", file_bytes=b"ok",
            filename="check.pdf", mime_type="application/pdf",
            video_file_id="vid", video_kind="video",
        )
        self.assertEqual(order.extra["payment_video_file_id"], "vid")
        self.assertIn("🎥 Видео перевода: есть", staff_card(order))
        data = [b.callback_data for row in support_order_kb(order).inline_keyboard for b in row]
        self.assertIn(f"support:video:{order.id}", data)
        self.assertIn(f"staff:trust:{order.id}", data)

    async def test_trusted_client_skips_video(self) -> None:
        from exchange.client_card import client_card
        from exchange.keyboards import support_order_kb
        from exchange.staff_card import staff_card

        # Отметили доверенным по прошлой заявке — активная тоже обновилась
        first = await self._paid_order(31)
        first = await self.orders.set_client_trusted(first, trusted=True, by_tg_id=2)
        self.assertFalse(first.extra["video_required"])
        self.assertTrue(await self.db.is_trusted(31))
        self.assertNotIn("запись экрана", client_card(first))
        self.assertIn("⭐ доверенный", staff_card(first))
        data = [b.callback_data for row in support_order_kb(first).inline_keyboard for b in row]
        self.assertIn(f"staff:untrust:{first.id}", data)

        # Новая заявка доверенного — сразу без видео
        await self.orders.cancel(first, reason="тест")
        second = await self._paid_order(31)
        self.assertFalse(second.extra["video_required"])

        # Убрали из доверенных — снова нужно видео
        second = await self.orders.set_client_trusted(second, trusted=False, by_tg_id=2)
        self.assertTrue(second.extra["video_required"])
        self.assertFalse(await self.db.is_trusted(31))

    def test_help_has_no_screenshot(self) -> None:
        from exchange.handlers.common import help_text

        text = help_text(_settings())
        self.assertNotIn("скриншот", text.lower())
        self.assertIn("PDF", text)
        self.assertIn("видео перевода", text)

    def test_pdf_detection(self) -> None:
        from types import SimpleNamespace

        from exchange.handlers.client import _is_pdf

        self.assertTrue(_is_pdf(SimpleNamespace(mime_type="application/pdf", file_name="a")))
        self.assertTrue(_is_pdf(SimpleNamespace(mime_type=None, file_name="Чек.PDF")))
        self.assertFalse(_is_pdf(SimpleNamespace(mime_type="image/jpeg", file_name="a.jpg")))


class ReceiptFlowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """
    Сквозной сценарий через диспетчер бота (Telegram подменён):
    «Я оплатил» → PDF → видео / «Нет видео».
    """

    async def asyncSetUp(self) -> None:
        from datetime import datetime, timezone

        from aiogram import Bot, Dispatcher
        from aiogram.client.session.base import BaseSession
        from aiogram.fsm.storage.memory import MemoryStorage
        from aiogram.methods import GetFile, GetMe, SendMessage
        from aiogram.types import Chat, File, Message, User

        from exchange.context import AppContext, ContextMiddleware
        from exchange.handlers import setup_routers
        from exchange.rates import RateService
        from exchange.staff_panel import StaffPanel

        sent = self.sent = []

        class FakeSession(BaseSession):
            async def make_request(self, bot, method, timeout=None):
                if isinstance(method, SendMessage):
                    sent.append(method.text)
                    return Message(
                        message_id=len(sent), date=datetime.now(timezone.utc),
                        chat=Chat(id=method.chat_id, type="private"), text=method.text,
                    )
                if isinstance(method, GetMe):
                    return User(id=999, is_bot=True, first_name="bot", username="testbot")
                if isinstance(method, GetFile):
                    return File(file_id=method.file_id, file_unique_id="u", file_path="f.pdf")
                return True

            async def stream_content(self, url, headers=None, timeout=30,
                                     chunk_size=65536, raise_for_status=True):
                yield b"%PDF-1.4 ok"

            async def close(self):
                pass

        self.tmp = tempfile.TemporaryDirectory()
        db_path = Path(self.tmp.name) / "t.db"
        settings = _settings(database_path=db_path)
        self.db = Database(db_path)
        await self.db.connect()
        self.bot = Bot("123:abc", session=FakeSession())
        panel = StaffPanel(self.bot, settings, self.db)
        self.orders = OrderService(
            db=self.db, settings=settings, receipt_checker=MockReceiptChecker(),
            on_change=panel.sync,
        )
        ctx = AppContext(settings=settings, db=self.db, orders=self.orders,
                         rates=RateService(settings), panel=panel)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.dp.update.middleware(ContextMiddleware(ctx))
        setup_routers(self.dp)
        self.upd = 0

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.tmp.cleanup()

    async def _feed(self, user_id: int, *, data: str | None = None, **msg) -> None:
        from datetime import datetime, timezone

        from aiogram.types import CallbackQuery, Chat, Message, Update, User

        self.upd += 1
        user = User(id=user_id, is_bot=False, first_name="C", username="c")
        chat = Chat(id=user_id, type="private")
        now = datetime.now(timezone.utc)
        if data is not None:
            m = Message(message_id=500 + self.upd, date=now, chat=chat, text="card")
            update = Update(update_id=self.upd, callback_query=CallbackQuery(
                id=str(self.upd), from_user=user, chat_instance="x", message=m, data=data))
        else:
            update = Update(update_id=self.upd, message=Message(
                message_id=self.upd, date=now, chat=chat, from_user=user, **msg))
        await self.dp.feed_update(self.bot, update)

    async def _order_waiting_payment(self, client_id: int):
        order = await self.orders.create_order(
            client_tg_id=client_id, client_username="c", amount_rub=5000, usdt_address="",
        )
        return await self.orders.assign_requisites(
            order, support_tg_id=2, requisites=Requisites(bank="Сбер", detail="+7900")
        )

    def _pdf(self):
        from aiogram.types import Document

        return {"document": Document(file_id="pdf1", file_unique_id="p1",
                                     file_name="чек.pdf", mime_type="application/pdf")}

    async def test_photo_rejected_pdf_then_video(self) -> None:
        from aiogram.types import PhotoSize, Video

        order = await self._order_waiting_payment(40)
        await self._feed(40, data=f"client:upload:{order.id}")
        self.assertIn("чек в формате PDF", self.sent[-1])
        # Фото не принимаем
        await self._feed(40, photo=[PhotoSize(file_id="ph", file_unique_id="ph", width=1, height=1)])
        self.assertIn("Принимаем только", self.sent[-1])
        # PDF → просим видео
        await self._feed(40, **self._pdf())
        self.assertIn("Шаг 2 из 2", self.sent[-1])
        # Видео → чек уходит на проверку вместе с видео
        await self._feed(40, video=Video(file_id="vid1", file_unique_id="v1",
                                         width=1, height=1, duration=5))
        order = await self.db.get_order_by_id(order.id)
        self.assertEqual(order.status, OrderStatus.AWAITING_SUPPORT_REVIEW)
        self.assertEqual(order.receipt_file_id, "pdf1")
        self.assertEqual(order.extra["payment_video_file_id"], "vid1")

    async def test_no_video_not_trusted_goes_to_support(self) -> None:
        order = await self._order_waiting_payment(41)
        await self._feed(41, data=f"client:upload:{order.id}")
        await self._feed(41, **self._pdf())
        await self._feed(41, data="client:novideo")
        self.assertIn("Georgina771", self.sent[-1])
        order = await self.db.get_order_by_id(order.id)
        self.assertEqual(order.status, OrderStatus.AWAITING_PAYMENT)  # ждёт видео/оператора
        self.assertTrue(order.extra.get("no_video"))

    async def test_no_video_trusted_goes_on(self) -> None:
        order = await self._order_waiting_payment(42)
        order = await self.orders.set_client_trusted(order, trusted=True, by_tg_id=1)
        await self._feed(42, data=f"client:upload:{order.id}")
        await self._feed(42, **self._pdf())
        await self._feed(42, data="client:novideo")
        order = await self.db.get_order_by_id(order.id)
        self.assertEqual(order.status, OrderStatus.AWAITING_SUPPORT_REVIEW)
        self.assertIsNone(order.extra.get("payment_video_file_id"))


if __name__ == "__main__":
    unittest.main()
