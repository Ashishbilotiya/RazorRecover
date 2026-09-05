"""Pydantic schemas for transaction-related API boundaries.

See CLAUDE.md coding rule 3.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TransactionSummary(BaseModel):
    """Compact view of a Razorpay-derived transaction row."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    razorpay_payment_id: str
    razorpay_order_id: str | None = None
    customer_id: str | None = None
    amount: int = Field(default=0, ge=0, description="Amount in paise.")
    currency: str = "INR"
    payment_method: str | None = None
    status: str
    failure_reason: str | None = None
    error_code: str | None = None
    created_at: datetime


__all__ = ["TransactionSummary"]
