"""Audit logger — append-only decision trail.

Every meaningful decision writes one row to ``audit_logs``. The writer accepts
an open SQLAlchemy ``Session`` and flushes immediately so the caller is sure
the record is persisted (used by the webhook flow which commits the whole
transaction in one go).

See CLAUDE.md section 27 — keep entries concise; never store private
chain-of-thought, only structured ``decision`` + ``reason`` + ``metadata``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.db.models import AuditLog


def record(
    session: Session,
    *,
    event_type: str,
    actor: str = "system",
    decision: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    recovery_case_id: str | None = None,
    transaction_id: str | None = None,
    webhook_event_id: str | None = None,
) -> AuditLog:
    """Persist an audit event and return the saved row.

    Callers are responsible for committing the surrounding transaction.
    """
    entry = AuditLog(
        event_type=event_type,
        actor=actor,
        decision=decision,
        reason=reason,
        event_metadata=metadata,
        recovery_case_id=recovery_case_id,
        transaction_id=transaction_id,
        webhook_event_id=webhook_event_id,
    )
    session.add(entry)
    session.flush()
    return entry


# Standard event_type constants — keep them centralized so callers don't
# reinvent the vocabulary.
WEBHOOK_RECEIVED = "webhook.received"
WEBHOOK_SIGNATURE_INVALID = "webhook.signature_invalid"
WEBHOOK_DUPLICATE = "webhook.duplicate"
WEBHOOK_NORMALIZED = "webhook.normalized"
WEBHOOK_REJECTED = "webhook.rejected"
WEBHOOK_PIPELINE_DEFERRED = "webhook.pipeline_deferred"

# Recovery decision-chain events (Phase 4).
RECOVERY_CASE_CREATED = "recovery.case_created"
POLICY_DECISION = "policy.decision"
SAFEGUARD_DECISION = "safeguard.decision"
EXECUTION_ATTEMPTED = "execution.attempted"
EXECUTION_SUCCEEDED = "execution.succeeded"
EXECUTION_FAILED = "execution.failed"
EXECUTION_BLOCKED = "execution.blocked"
EXECUTION_DUPLICATE = "execution.duplicate"
OUTCOME_RECORDED = "outcome.recorded"

# Phase 5 — API-level events.
CASE_APPROVED = "case.approved"
CASE_APPROVAL_REJECTED = "case.approval_rejected"
EXECUTION_SKIPPED = "execution.skipped"
PIPELINE_ERROR = "pipeline.error"
WEBHOOK_PIPELINE_TRIGGERED = "webhook.pipeline_triggered"


__all__ = [
    "CASE_APPROVAL_REJECTED",
    "CASE_APPROVED",
    "EXECUTION_ATTEMPTED",
    "EXECUTION_BLOCKED",
    "EXECUTION_DUPLICATE",
    "EXECUTION_FAILED",
    "EXECUTION_SKIPPED",
    "EXECUTION_SUCCEEDED",
    "OUTCOME_RECORDED",
    "PIPELINE_ERROR",
    "POLICY_DECISION",
    "RECOVERY_CASE_CREATED",
    "SAFEGUARD_DECISION",
    "WEBHOOK_DUPLICATE",
    "WEBHOOK_NORMALIZED",
    "WEBHOOK_PIPELINE_DEFERRED",
    "WEBHOOK_PIPELINE_TRIGGERED",
    "WEBHOOK_RECEIVED",
    "WEBHOOK_REJECTED",
    "WEBHOOK_SIGNATURE_INVALID",
    "record",
]
