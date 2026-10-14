from aiogram.types import User


def telegram_full_name(user: User) -> str:
    parts = [user.first_name]
    if user.last_name:
        parts.append(user.last_name)
    name = " ".join(parts).strip()
    return name or str(user.id)
