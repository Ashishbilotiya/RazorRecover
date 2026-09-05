"""Pydantic schemas for recovery-case and recovery-action API boundaries.

"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.schemas.transaction import TransactionSummary


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------
class CaseSummary(BaseModel):
    """Summary view of a recovery case (list endpoint)."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    transaction_id: str | None = None
    customer_id: str | None = None
    amount: float = Field(default=0.0, ge=0.0)
    revenue_at_risk: float = Field(default=0.0, ge=0.0)
    recovery_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    root_cause: str | None = None
    recommended_action: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: str
    amount_recovered: float = Field(default=0.0, ge=0.0)
    created_at: datetime
    updated_at: datetime


class RecoveryActionOut(BaseModel):
    """A single recovery action attempt."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    recovery_case_id: str
    action_type: str
    status: str
    reason: str | None = None
    attempt_number: int = Field(default=1, ge=1)
    executed_at: datetime | None = None
    result: dict | None = None


class CaseDetail(CaseSummary):
    """Detail view of a recovery case (single case endpoint)."""

    transaction: TransactionSummary | None = None
    actions: list[RecoveryActionOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Approval endpoint
# ---------------------------------------------------------------------------
class ApprovalResponse(BaseModel):
    """Returned by POST /api/recovery/cases/{case_id}/approve."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: Literal["approved"]
    approved_at: datetime
    message: str = "Recovery case approved for execution."


# ---------------------------------------------------------------------------
# Execution endpoint
# ---------------------------------------------------------------------------
class ExecutionResponse(BaseModel):
    """Returned by POST /api/recovery/cases/{case_id}/execute."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: Literal["executing", "succeeded", "failed"]
    action_type: str | None = None
    amount_recovered: float = Field(default=0.0, ge=0.0)
    external_reference: str | None = None
    idempotency_key: str
    already_executed: bool = False
    executed_at: datetime | None = None
    error_code: str | None = None
    message: str = ""


# ---------------------------------------------------------------------------
# Audit timeline
# ---------------------------------------------------------------------------
class AuditEventOut(BaseModel):
    """One row in the chronological audit timeline for a case."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str
    event_type: str
    actor: str
    decision: str | None = None
    reason: str | None = None
    metadata_: dict | None = Field(default=None, alias="metadata")
    created_at: datetime

    @classmethod
    def from_orm_row(cls, row) -> "AuditEventOut":
        """Build an instance from a raw ``AuditLog`` ORM row.

        The DB column maps to the Python attribute ``event_metadata``. The
        bare name ``metadata`` on the SQLAlchemy ``Base`` class is the
        declarative ``MetaData()`` registry, so Pydantic's attribute lookup
        would pick that up unless we read the real attribute manually.
        """
        return cls(
            id=row.id,
            event_type=row.event_type,
            actor=row.actor,
            decision=row.decision,
            reason=row.reason,
            metadata_=row.event_metadata,
            created_at=row.created_at,
        )


__all__ = [
    "ApprovalResponse",
    "AuditEventOut",
    "CaseDetail",
    "CaseSummary",
    "ExecutionResponse",
    "RecoveryActionOut",
]
