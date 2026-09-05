"""Pydantic schema for the analytics overview endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalyticsOverview(BaseModel):
    """All metrics returned by GET /api/analytics/overview.

    All values come from SQL aggregates over the persisted DB. Zero on empty
    — never invent metrics. Amounts are in rupees (the engine divides paise
    by 100 before storing on ``recovery_cases``).
    """

    model_config = ConfigDict(extra="forbid")

    total_transactions: int = Field(default=0, ge=0)
    total_failed_transactions: int = Field(default=0, ge=0)
    recovery_cases: int = Field(default=0, ge=0)

    revenue_at_risk: float = Field(default=0.0, ge=0.0)
    revenue_targeted: float = Field(default=0.0, ge=0.0)
    revenue_recovered: float = Field(default=0.0, ge=0.0)
    recovery_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    successful_actions: int = Field(default=0, ge=0)
    failed_actions: int = Field(default=0, ge=0)
    blocked_actions: int = Field(default=0, ge=0)
    human_escalations: int = Field(default=0, ge=0)
    intervention_success_rate: float = Field(default=0.0, ge=0.0, le=1.0)


__all__ = ["AnalyticsOverview"]
