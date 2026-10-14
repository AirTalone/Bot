from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str
    admin_ids: str = ""
    database_url: str = "sqlite+aiosqlite:///data/bot.db"
    payment_title: str = "Оплата VPN"
    payment_details: str = "Укажите реквизиты в PAYMENT_DETAILS"
    payment_qr_payload: str = ""
    support_contact: str = ""

    @field_validator("admin_ids", "payment_title", "payment_details", "payment_qr_payload", "support_contact")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @property
    def admin_id_list(self) -> list[int]:
        if not self.admin_ids:
            return []
        return [int(part.strip()) for part in self.admin_ids.split(",") if part.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
