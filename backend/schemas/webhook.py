"""Pydantic schemas for Razorpay webhook payloads (normalized).

Real Razorpay structure (verified against https://razorpay.com/docs/webhooks/payments/):
    {
      "entity": "event",
      "account_id": "acc_...",
      "event": "payment.failed",
      "contains": ["payment"],
      "payload": {
        "payment": {
          "entity": {
            "id": "pay_...",
            "amount": 1600,
            "status": "failed",
            "error_code": "BAD_REQUEST_ERROR",
            ...
          }
        }
      },
      "created_at": 1569334395
    }

The HTTP header ``X-Razorpay-Signature`` carries an HMAC-SHA256 of the raw body
signed with ``RAZORPAY_WEBHOOK_SECRET``. The optional ``X-Razorpay-Event-Id``
header carries a delivery id suitable for idempotency.

See CLAUDE.md sections 9, 25, 26.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

PaymentStatus = Literal[
    "created",
    "authorized",
    "captured",
    "refunded",
    "failed",
]
WebhookOutcome = Literal["accepted", "duplicate", "rejected"]


class RazorpayPaymentEntity(BaseModel):
    """Subset of Razorpay payment entity we care about.

    Real Razorpay payloads nest this under ``payload.payment.entity``.
    """

    model_config = ConfigDict(extra="allow")

    id: str = Field(..., description="Razorpay payment id (e.g. pay_...).")
    entity: Literal["payment"] = "payment"
    order_id: str | None = None
    amount: int = Field(..., description="Amount in paise.")
    currency: str = "INR"
    status: str
    method: str | None = None
    description: str | None = None
    email: str | None = None
    contact: str | None = None
    fee: int | None = None
    tax: int | None = None
    error_code: str | None = None
    error_description: str | None = None
    error_reason: str | None = None
    error_source: str | None = None
    error_step: str | None = None
    notes: dict[str, Any] | None = None
    captured: bool | None = None
    international: bool | None = None
    amount_refunded: int | None = None
    refund_status: str | None = None
    acquirer_data: dict[str, Any] | None = None
    created_at: int | None = None


class RazorpayPaymentWrapper(BaseModel):
    """Real Razorpay nests the payment entity under ``payload.payment.entity``."""

    model_config = ConfigDict(extra="allow")

    entity: RazorpayPaymentEntity


class RazorpayOrderEntity(BaseModel):
    """Subset of Razorpay order entity."""

    model_config = ConfigDict(extra="allow")

    id: str
    entity: Literal["order"] = "order"
    amount: int
    currency: str = "INR"
    status: str
    notes: dict[str, Any] | None = None
    customer_id: str | None = None
    created_at: int | None = None


class RazorpayOrderWrapper(BaseModel):
    """Real Razorpay nests the order entity under ``payload.order.entity``."""

    model_config = ConfigDict(extra="allow")

    entity: RazorpayOrderEntity


class RazorpayPayload(BaseModel):
    """The ``payload`` field of a Razorpay webhook envelope."""

    model_config = ConfigDict(extra="allow")

    payment: RazorpayPaymentWrapper | None = None
    order: RazorpayOrderWrapper | None = None


class RazorpayWebhookEnvelope(BaseModel):
    """Top-level Razorpay webhook envelope."""

    model_config = ConfigDict(extra="allow")

    entity: Literal["event"] = "event"
    account_id: str | None = None
    event: str = Field(..., description="e.g. payment.captured, payment.failed, order.paid.")
    contains: list[str] = Field(default_factory=list)
    payload: RazorpayPayload
    created_at: int | None = None


class WebhookResponse(BaseModel):
    """Standard response returned by POST /api/webhooks/razorpay."""

    outcome: WebhookOutcome
    external_event_id: str
    event_type: str
    transaction_id: str | None = None
    reason: str | None = None


__all__ = [
    "PaymentStatus",
    "RazorpayOrderEntity",
    "RazorpayOrderWrapper",
    "RazorpayPaymentEntity",
    "RazorpayPaymentWrapper",
    "RazorpayPayload",
    "RazorpayWebhookEnvelope",
    "WebhookOutcome",
    "WebhookResponse",
]