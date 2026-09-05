"""Pydantic schemas for the AI agent pipeline.

These are the contract between the agents, the orchestrator, and the future
policy engine (Phase 4). The Phase 4 layer never has to handle free-form text —
it consumes one of these models and applies deterministic rules.

"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class RootCauseCategory(str, Enum):
    TEMPORARY_PAYMENT_FAILURE = "TEMPORARY_PAYMENT_FAILURE"
    PERMANENT_PAYMENT_FAILURE = "PERMANENT_PAYMENT_FAILURE"
    PAYMENT_METHOD_ISSUE = "PAYMENT_METHOD_ISSUE"
    CUSTOMER_BEHAVIOR = "CUSTOMER_BEHAVIOR"
    GATEWAY_DEGRADATION = "GATEWAY_DEGRADATION"
    SUBSCRIPTION_FAILURE = "SUBSCRIPTION_FAILURE"
    CHECKOUT_ABANDONMENT = "CHECKOUT_ABANDONMENT"
    UNKNOWN = "UNKNOWN"


class RecoveryActionType(str, Enum):
    RETRY_PAYMENT = "RETRY_PAYMENT"
    SEND_PAYMENT_LINK = "SEND_PAYMENT_LINK"
    SEND_REMINDER = "SEND_REMINDER"
    SUGGEST_ALTERNATE_PAYMENT_METHOD = "SUGGEST_ALTERNATE_PAYMENT_METHOD"
    CHECKOUT_RECOVERY = "CHECKOUT_RECOVERY"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"
    STOP = "STOP"


# Failure reasons the LLM and the deterministic fallback both understand.
# Real Razorpay webhook failure reasons + synthetic dataset values.
TEMPORARY_FAILURE_REASONS = frozenset(
    {"temporary_timeout", "network_error", "gateway_degradation"}
)
PERMANENT_FAILURE_REASONS = frozenset(
    {"card_declined", "insufficient_funds", "authentication_failed"}
)
CUSTOMER_FAILURE_REASONS = frozenset({"user_cancelled"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _bounded_unit(value: float, *, name: str) -> float:
    if value < 0.0 or value > 1.0:
        raise ValueError(f"{name} must be within [0, 1], got {value}")
    return float(value)


def _non_negative(value: float, *, name: str) -> float:
    if value < 0.0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return float(value)


# ---------------------------------------------------------------------------
# Inputs to the pipeline
# ---------------------------------------------------------------------------
class TransactionContext(BaseModel):
    """Read-only context passed through the agent pipeline.

    Built by the webhook handler (Phase 1) / seed scripts / demo runner.
    Only fields with a clear business meaning are exposed so the LLM cannot
    invent facts.
    """

    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    amount: int = Field(..., ge=0, description="Amount in paise.")
    currency: str = Field(default="INR")
    payment_method: str | None = None
    failure_reason: str | None = None
    customer_id: str | None = None
    customer_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    customer_failure_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    previous_retry_count: int = Field(default=0, ge=0)
    merchant_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    payment_method_success_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    razorpay_order_id: str | None = None
    razorpay_payment_id: str | None = None


# ---------------------------------------------------------------------------
# Agent outputs
# ---------------------------------------------------------------------------
class RiskAssessment(BaseModel):
    """Structured output from the Risk Agent ."""

    model_config = ConfigDict(extra="forbid")

    is_recoverable: bool
    recovery_probability: float = Field(..., ge=0.0, le=1.0)
    revenue_at_risk: float = Field(..., ge=0.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., max_length=500)
    source: Literal["ml", "llm", "fallback"] = "ml"


class RootCauseAssessment(BaseModel):
    """Structured output from the Root Cause Agent """

    model_config = ConfigDict(extra="forbid")

    root_cause: RootCauseCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., max_length=500)
    source: Literal["llm", "fallback"] = "fallback"


class RecoveryRecommendation(BaseModel):
    """Structured output from the Recovery Agent.

    This is a *recommendation*. The policy engine in Phase 4 — never the
    agent — decides whether it can be executed.
    """

    model_config = ConfigDict(extra="forbid")

    action: RecoveryActionType
    confidence: float = Field(..., ge=0.0, le=1.0)
    reason: str = Field(..., max_length=500)
    expected_recovery: float = Field(..., ge=0.0)
    source: Literal["llm", "fallback"] = "fallback"


class AgentPipelineResult(BaseModel):
    """Result returned by the orchestrator ."""

    model_config = ConfigDict(extra="forbid")

    transaction_id: str
    risk: RiskAssessment
    root_cause: RootCauseAssessment
    recommendation: RecoveryRecommendation
    used_fallback: bool = Field(
        default=False,
        description="True if any of the three agents fell back to deterministic rules.",
    )


# Field-level validators that callers can opt into by adding them to their
# own models — kept here as references.
__all__ = [
    "AgentPipelineResult",
    "CUSTOMER_FAILURE_REASONS",
    "PERMANENT_FAILURE_REASONS",
    "RecoveryActionType",
    "RecoveryRecommendation",
    "RiskAssessment",
    "RootCauseAssessment",
    "RootCauseCategory",
    "TEMPORARY_FAILURE_REASONS",
    "TransactionContext",
]


# Silences unused-helper warnings; the helpers are reused via validators.
_ = field_validator
_ = (_bounded_unit, _non_negative)
