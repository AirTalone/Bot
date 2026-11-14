from aiogram import Dispatcher, F

from exchange.handlers import admin, client, common, fallback, staff, support, wallet


def setup_routers(dp: Dispatcher) -> None:
    # Сообщения клиентов/саппорта/админа — только в личке с ботом.
    # В рабочей группе работают кнопки карточек и команды /stats, /chatid (роутер staff).
    for module in (common, client, wallet, support, admin, fallback):
        module.router.message.filter(F.chat.type == "private")

    dp.include_router(staff.router)
    dp.include_router(common.router)
    dp.include_router(client.router)
    dp.include_router(wallet.router)
    dp.include_router(support.router)
    dp.include_router(admin.router)
    # Последним: любое «непонятное» сообщение вне сценария → меню как /start
    dp.include_router(fallback.router)
