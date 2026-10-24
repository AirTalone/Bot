from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models import Order
from bot.services.orders import fulfill_order
from bot.services.panel.base import PanelClient, PanelError

_USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


def panel_username_for_telegram(telegram_id: int) -> str:
    candidate = f"tg{telegram_id}"
    if not _USERNAME_RE.fullmatch(candidate):
        raise PanelError(f"cannot build panel username from telegram_id={telegram_id}")
    return candidate


async def provision_and_fulfill(
    session: AsyncSession,
    order: Order,
    panel: PanelClient,
) -> Order:
    username = order.panel_username or panel_username_for_telegram(order.user.telegram_id)
    access = await panel.ensure_subscription(
        username=username,
        duration_days=order.duration_days,
        note=f"order:{order.id} code:{order.payment_code}",
    )
    fulfilled = await fulfill_order(
        session,
        order.id,
        access.subscription_url,
        panel_username=access.username,
        expires_at=access.expires_at,
    )
    if fulfilled is None:
        raise PanelError("order is no longer pending_review")
    return fulfilled
