"""Pydantic schemas for the recovery decision chain.

These are the contract between policy, safeguards, executor, and the engine.
Nothing else produces or consumes them.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.agents.schemas import RecoveryActionType, RecoveryRecommendation


# ---------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------
class PolicyVerdict(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class PolicyRule(str, Enum):
    HIGH_CONFIDENCE_TEMPORARY_RETRY = "HIGH_CONFIDENCE_TEMPORARY_RETRY"
    HIGH_CONFIDENCE_PERMANENT_ALTERNATE = "HIGH_CONFIDENCE_PERMANENT_ALTERNATE"
    HIGH_VALUE_PAYMENT_LINK = "HIGH_VALUE_PAYMENT_LINK"
    CUSTOMER_CANCELLED_REMINDER = "CUSTOMER_CANCELLED_REMINDER"
    GATEWAY_DEGRADATION_CHECKOUT_RECOVERY = "GATEWAY_DEGRADATION_CHECKOUT_RECOVERY"
    LOW_CONFIDENCE_ESCALATE = "LOW_CONFIDENCE_ESCALATE"
    NO_ACTION_NEEDED = "NO_ACTION_NEEDED"
    ACTION_NOT_PERMITTED = "ACTION_NOT_PERMITTED"
    RETRY_LIMIT_EXCEEDED = "RETRY_LIMIT_EXCEEDED"
    AMOUNT_ESCALATION = "AMOUNT_ESCALATION"
    PAYMENT_ALREADY_SUCCEEDED = "PAYMENT_ALREADY_SUCCEEDED"


class PolicyDecision(BaseModel):
    """Result of the policy engine (CLAUDE.md section 22)."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    verdict: PolicyVerdict
    action: RecoveryActionType | None = Field(
        default=None,
        description="Action the executor is allowed to take; None on reject/escalate.",
    )
    policy_rule: PolicyRule
    reason: str = Field(..., max_length=500)
    required_safeguards: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Safeguards
# ---------------------------------------------------------------------------
class SafeguardName(str, Enum):
    IDEMPOTENCY = "IDEMPOTENCY"
    MAX_RETRY_COUNT = "MAX_RETRY_COUNT"
    MAX_AMOUNT = "MAX_AMOUNT"
    MIN_PROBABILITY = "MIN_PROBABILITY"
    PAYMENT_ALREADY_SUCCEEDED = "PAYMENT_ALREADY_SUCCEEDED"
    TRANSACTION_VALID = "TRANSACTION_VALID"
    ACTION_PERMITTED = "ACTION_PERMITTED"


class SafeguardDecision(BaseModel):
    """Result of the safeguards gate (CLAUDE.md section 23)."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool
    failed_safeguard: SafeguardName | None = None
    reason: str = Field(..., max_length=500)
    details: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------
class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ExecutionResult(BaseModel):
    """One execution attempt's outcome (CLAUDE.md section 24)."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    status: ExecutionStatus
    action: RecoveryActionType
    external_reference: str | None = None
    amount: int = Field(default=0, ge=0)
    message: str = Field(..., max_length=500)
    executed_at: datetime
    error_code: str | None = None


# ---------------------------------------------------------------------------
# Recovery case outcomes
# ---------------------------------------------------------------------------
class RecoveryCaseStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


class RecoveryOutcome(BaseModel):
    """Top-level result returned by the recovery engine."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    transaction_id: str
    recommendation: RecoveryRecommendation
    policy: PolicyDecision
    safeguard: SafeguardDecision
    execution: ExecutionResult | None = None
    case_status: RecoveryCaseStatus
    blocked_reason: str | None = None
    created_at: datetime


__all__ = [
    "ExecutionResult",
    "ExecutionStatus",
    "PolicyDecision",
    "PolicyRule",
    "PolicyVerdict",
    "RecoveryCaseStatus",
    "RecoveryOutcome",
    "SafeguardDecision",
    "SafeguardName",
]