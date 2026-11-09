from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from exchange.config import Settings
from exchange.db import Database
from exchange.rates import RateService
from exchange.services import OrderService


@dataclass
class AppContext:
    settings: Settings
    db: Database
    orders: OrderService
    rates: RateService


class ContextMiddleware(BaseMiddleware):
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        data["ctx"] = self.ctx
        data["settings"] = self.ctx.settings
        data["orders"] = self.ctx.orders
        data["db"] = self.ctx.db
        data["rates"] = self.ctx.rates
        return await handler(event, data)
