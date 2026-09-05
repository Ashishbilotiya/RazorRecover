

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
class Customer(Base, TimestampMixin):
    """A customer who transacts with the merchant.

    `external_customer_id` is the merchant/Razorpay reference. We never store
    PII beyond what the merchant sends.
    """

    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_customer_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total_transactions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_transactions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_transactions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_spend: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    average_order_value: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    last_successful_payment: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    transactions: Mapped[list["Transaction"]] = relationship(
        back_populates="customer", cascade="save-update"
    )


# ---------------------------------------------------------------------------
# Order + Transaction
# ---------------------------------------------------------------------------
class Order(Base, TimestampMixin):
    """A Razorpay order (created before a payment attempt)."""

    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    razorpay_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # paise
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    notes: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Transaction(Base, TimestampMixin):
    """A single payment attempt captured from Razorpay webhooks."""

    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("razorpay_payment_id", name="uq_transaction_razorpay_payment_id"),
        Index("ix_transaction_status_created", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    razorpay_payment_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("orders.razorpay_order_id"), nullable=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)  # paise
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    payment_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    customer: Mapped[Customer | None] = relationship(back_populates="transactions")


# ---------------------------------------------------------------------------
# WebhookEvent
# ---------------------------------------------------------------------------
class WebhookEvent(Base, TimestampMixin):
    """A raw Razorpay webhook, kept for idempotency + replay debugging."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("external_event_id", name="uq_webhook_external_event_id"),
        Index("ix_webhook_event_type_created", "event_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    external_event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(64), nullable=True)
    account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    payload_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    processed: Mapped[bool] = mapped_column(default=False, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------
class AuditLog(Base):
    """Append-only audit trail for decisions and side effects."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_event_type_created", "event_type", "created_at"),
        Index("ix_audit_recovery_case_id", "recovery_case_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[str] = mapped_column(String(64), default="system", nullable=False)
    decision: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    recovery_case_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    webhook_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )


# ---------------------------------------------------------------------------
# Skeletons for later phases (declared now so Alembic migrations stay simple).
# ---------------------------------------------------------------------------
class RecoveryCase(Base, TimestampMixin):
    """Skeleton — populated in Phase 4 by recovery/policies.py."""

    __tablename__ = "recovery_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    transaction_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), nullable=True
    )
    customer_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("customers.id"), nullable=True
    )
    amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    revenue_at_risk: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    recovery_probability: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    root_cause: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    amount_recovered: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)


class RecoveryAction(Base, TimestampMixin):
    """Skeleton — populated in Phase 4 by recovery/executor.py."""

    __tablename__ = "recovery_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    recovery_case_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("recovery_cases.id"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)


__all__ = [
    "AuditLog",
    "Customer",
    "Order",
    "RecoveryAction",
    "RecoveryCase",
    "TimestampMixin",
    "Transaction",
    "WebhookEvent",
]
