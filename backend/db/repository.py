"""Repository / data access layer. Keep query logic out of API handlers.

Phase 4 adds :class:`RecoveryCaseRepository` and helpers for executing
recovery actions idempotently. The repository never calls Razorpay.

See CLAUDE.md coding rule 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy.orm import Session

from backend.db.models import Customer, RecoveryAction, RecoveryCase, Transaction


# ---------------------------------------------------------------------------
# Recovery-case repositories
# ---------------------------------------------------------------------------
@dataclass
class CaseLookup:
    """Read-side lookup helpers for the recovery engine."""

    @staticmethod
    def get_case_by_transaction(session: Session, transaction_id: str) -> RecoveryCase | None:
        return (
            session.query(RecoveryCase)
            .filter(RecoveryCase.transaction_id == transaction_id)
            .one_or_none()
        )

    @staticmethod
    def get_case(session: Session, case_id: str) -> RecoveryCase | None:
        return session.query(RecoveryCase).filter(RecoveryCase.id == case_id).one_or_none()

    @staticmethod
    def list_cases(
        session: Session, *, limit: int = 50, offset: int = 0
    ) -> Sequence[RecoveryCase]:
        return (
            session.query(RecoveryCase)
            .order_by(RecoveryCase.created_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    @staticmethod
    def actions_for_case(session: Session, case_id: str) -> Sequence[RecoveryAction]:
        return (
            session.query(RecoveryAction)
            .filter(RecoveryAction.recovery_case_id == case_id)
            .order_by(RecoveryAction.created_at.asc())
            .all()
        )


@dataclass
class CaseWriter:
    """Write-side helpers used by the recovery engine."""

    @staticmethod
    def create_case(
        session: Session,
        *,
        transaction: Transaction,
        customer: Customer | None,
        amount: float,
        revenue_at_risk: float,
        recovery_probability: float,
        root_cause: str | None,
        recommended_action: str | None,
        confidence: float,
        status: str = "pending",
    ) -> RecoveryCase:
        case = RecoveryCase(
            transaction_id=transaction.id,
            customer_id=customer.id if customer is not None else None,
            amount=amount,
            revenue_at_risk=revenue_at_risk,
            recovery_probability=recovery_probability,
            root_cause=root_cause,
            recommended_action=recommended_action,
            confidence=confidence,
            status=status,
        )
        session.add(case)
        session.flush()
        return case

    @staticmethod
    def update_case(
        session: Session,
        case: RecoveryCase,
        *,
        status: str | None = None,
        amount_recovered: float | None = None,
    ) -> RecoveryCase:
        if status is not None:
            case.status = status
        if amount_recovered is not None:
            case.amount_recovered = amount_recovered
        session.flush()
        return case

    @staticmethod
    def record_action(
        session: Session,
        *,
        case: RecoveryCase,
        action_type: str,
        status: str,
        reason: str | None = None,
        attempt_number: int = 1,
        executed_at,
        result: dict | None = None,
    ) -> RecoveryAction:
        action = RecoveryAction(
            recovery_case_id=case.id,
            action_type=action_type,
            status=status,
            reason=reason,
            attempt_number=attempt_number,
            executed_at=executed_at,
            result=result,
        )
        session.add(action)
        session.flush()
        return action

    @staticmethod
    def idempotent_existing(
        session: Session, *, case_id: str, idempotency_key: str
    ) -> RecoveryAction | None:
        """Return an existing successful action matching ``idempotency_key``.

        The ``result`` JSON column holds the key so we can detect replays
        even after the action row has been updated.
        """
        candidates = (
            session.query(RecoveryAction)
            .filter(RecoveryAction.recovery_case_id == case_id)
            .all()
        )
        for action in candidates:
            if action.result and action.result.get("idempotency_key") == idempotency_key:
                return action
        return None


__all__ = [
    "CaseLookup",
    "CaseWriter",
]