

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import AuditLog, RecoveryAction, RecoveryCase, Transaction
from backend.recovery.schemas import ExecutionStatus, RecoveryCaseStatus
from backend.schemas.analytics import AnalyticsOverview

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


# Statuses for which we count the case amount as "targeted revenue":
# anything we acted on (or at least approved for action).
_TARGETED_STATUSES = (
    RecoveryCaseStatus.APPROVED.value,
    RecoveryCaseStatus.EXECUTING.value,
    RecoveryCaseStatus.SUCCEEDED.value,
    RecoveryCaseStatus.FAILED.value,
)


@router.get("/overview", response_model=AnalyticsOverview)
def get_analytics_overview(session: Session = Depends(get_db)) -> AnalyticsOverview:
    """Return aggregate business metrics derived from persisted rows."""

    total_tx = session.scalar(select(func.count(Transaction.id))) or 0
    failed_tx = (
        session.scalar(
            select(func.count(Transaction.id)).where(Transaction.status == "failed")
        )
        or 0
    )
    recovery_cases = session.scalar(select(func.count(RecoveryCase.id))) or 0

    # Amounts in RecoveryCase are stored in RUPEES (engine divides by 100).
    revenue_at_risk = (
        session.scalar(
            select(func.coalesce(func.sum(RecoveryCase.revenue_at_risk), 0.0))
        )
        or 0.0
    )
    revenue_targeted = (
        session.scalar(
            select(func.coalesce(func.sum(RecoveryCase.amount), 0.0)).where(
                RecoveryCase.status.in_(_TARGETED_STATUSES)
            )
        )
        or 0.0
    )
    revenue_recovered = (
        session.scalar(
            select(func.coalesce(func.sum(RecoveryCase.amount_recovered), 0.0)).where(
                RecoveryCase.status == RecoveryCaseStatus.SUCCEEDED.value
            )
        )
        or 0.0
    )

    recovery_rate = (
        revenue_recovered / revenue_targeted if revenue_targeted > 0 else 0.0
    )

    successful_actions = (
        session.scalar(
            select(func.count(RecoveryAction.id)).where(
                RecoveryAction.status == ExecutionStatus.SUCCESS.value
            )
        )
        or 0
    )
    failed_actions = (
        session.scalar(
            select(func.count(RecoveryAction.id)).where(
                RecoveryAction.status == ExecutionStatus.FAILED.value
            )
        )
        or 0
    )
    blocked_actions = (
        session.scalar(
            select(func.count(RecoveryCase.id)).where(
                RecoveryCase.status == RecoveryCaseStatus.BLOCKED.value
            )
        )
        or 0
    )

    # Human escalations: audit rows whose event_type='policy.decision' and
    # whose metadata carries a policy_rule of LOW_CONFIDENCE_ESCALATE or
    # AMOUNT_ESCALATION. ``func.json_extract`` is portable across SQLite
    # (test runs) and PostgreSQL (production).
    escalation_rules = ("LOW_CONFIDENCE_ESCALATE", "AMOUNT_ESCALATION")
    policy_rule_expr = func.json_extract(AuditLog.event_metadata, "$.policy_rule")
    human_escalations = (
        session.scalar(
            select(func.count(AuditLog.id))
            .where(AuditLog.event_type == "policy.decision")
            .where(policy_rule_expr.in_(escalation_rules))
        )
        or 0
    )

    total_actions = successful_actions + failed_actions
    intervention_success_rate = (
        successful_actions / total_actions if total_actions > 0 else 0.0
    )

    return AnalyticsOverview(
        total_transactions=total_tx,
        total_failed_transactions=failed_tx,
        recovery_cases=recovery_cases,
        revenue_at_risk=revenue_at_risk,
        revenue_targeted=revenue_targeted,
        revenue_recovered=revenue_recovered,
        recovery_rate=recovery_rate,
        successful_actions=successful_actions,
        failed_actions=failed_actions,
        blocked_actions=blocked_actions,
        human_escalations=human_escalations,
        intervention_success_rate=intervention_success_rate,
    )


__all__ = ["router"]
