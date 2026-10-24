import enum
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class OrderStatus(enum.StrEnum):
    awaiting_payment = "awaiting_payment"
    pending_review = "pending_review"
    fulfilled = "fulfilled"
    rejected = "rejected"
    cancelled = "cancelled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Tariff(Base):
    __tablename__ = "tariffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(128))
    duration_days: Mapped[int]
    price_minor: Mapped[int]
    stars_price: Mapped[int] = mapped_column(default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    tariff_id: Mapped[int] = mapped_column(ForeignKey("tariffs.id"))
    payment_code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    price_minor: Mapped[int]
    tariff_title: Mapped[str] = mapped_column(String(128))
    duration_days: Mapped[int]
    status: Mapped[str] = mapped_column(String(32), index=True)
    payment_method: Mapped[str] = mapped_column(String(16), default="qr")
    stars_amount: Mapped[int | None] = mapped_column(nullable=True)
    telegram_payment_charge_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    access_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    panel_username: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(lazy="raise")
    tariff: Mapped[Tariff] = relationship(lazy="raise")


class RuntimeState(Base):
    """Singleton-ish row (id=1) for operator toggles."""

    __tablename__ = "runtime_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    maintenance: Mapped[bool] = mapped_column(Boolean, default=False)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
