from aiogram import Dispatcher

from exchange.handlers import admin, client, common, support, wallet


def setup_routers(dp: Dispatcher) -> None:
    dp.include_router(common.router)
    dp.include_router(client.router)
    dp.include_router(wallet.router)
    dp.include_router(support.router)
    dp.include_router(admin.router)
