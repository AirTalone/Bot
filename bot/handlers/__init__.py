from bot.handlers.admin import router as admin_router
from bot.handlers.payments import router as payments_router
from bot.handlers.user import router as user_router

__all__ = ["admin_router", "payments_router", "user_router"]
