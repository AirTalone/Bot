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
        self.assertAlmostEqual(order.amount_usdt, round(5000 / 101.0, 6))

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


if __name__ == "__main__":
    unittest.main()
