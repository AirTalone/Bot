from aiogram.filters import Filter
from aiogram.types import TelegramObject

from bot.config import Settings


class IsAdmin(Filter):
    async def __call__(self, event: TelegramObject, settings: Settings) -> bool:
        user = getattr(event, "from_user", None)
        return user is not None and user.id in settings.admin_id_list
