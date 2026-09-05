"""Recovery-case API endpoints.

The API never talks to Razorpay directly — only the engine's
``execute_approved_case`` does, via the executor. The endpoints here are a
thin layer over ``backend.recovery.engine.RecoveryEngine`` plus repository
reads.

Endpoints (see CLAUDE.md section 42):

    GET    /api/recovery/cases
    GET    /api/recovery/cases/{case_id}
    POST   /api/recovery/cases/{case_id}/approve
    POST   /api/recovery/cases/{case_id}/execute
    GET    /api/audit/{case_id}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.audit import logger as audit
from backend.db.database import get_db, get_session_factory
from backend.db.models import AuditLog, RecoveryCase, RecoveryAction, Transaction
from backend.db.repository import CaseLookup, CaseWriter
from backend.recovery.engine import (
    AlreadyExecuted,
    CaseNotEligible,
    CaseNotFound,
    RecoveryEngine,
)
from backend.recovery.schemas import (
    ExecutionStatus,
    RecoveryCaseStatus,
)
from backend.schemas.recovery import (
    ApprovalResponse,
    AuditEventOut,
    CaseDetail,
    CaseSummary,
    ExecutionResponse,
    RecoveryActionOut,
)
from backend.schemas.transaction import TransactionSummary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["recovery"])


# ---------------------------------------------------------------------------
# Listing + detail
# ---------------------------------------------------------------------------
@router.get("/recovery/cases", response_model=list[CaseSummary])
def list_recovery_cases(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by case status (pending, approved, succeeded, ...).",
    ),
    action: str | None = Query(
        default=None,
        description="Filter by recommended action (RETRY_PAYMENT, ...).",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_db),
) -> list[CaseSummary]:
    query = session.query(RecoveryCase).order_by(RecoveryCase.created_at.desc())
    if status_filter is not None:
        query = query.filter(RecoveryCase.status == status_filter.lower())
    if action is not None:
        query = query.filter(RecoveryCase.recommended_action == action)
    rows = query.offset(offset).limit(limit).all()
    return [CaseSummary.model_validate(row) for row in rows]


@router.get("/recovery/cases/{case_id}", response_model=CaseDetail)
def get_recovery_case(
    case_id: str,
    session: Session = Depends(get_db),
) -> CaseDetail:
    case = CaseLookup.get_case(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="recovery case not found")

    transaction = (
        session.get(Transaction, case.transaction_id)
        if case.transaction_id
        else None
    )
    actions = CaseLookup.actions_for_case(session, case.id)

    detail = CaseSummary.model_validate(case).model_dump()
    detail["transaction"] = (
        TransactionSummary.model_validate(transaction) if transaction else None
    )
    detail["actions"] = [RecoveryActionOut.model_validate(a) for a in actions]
    return CaseDetail.model_validate(detail)


# ---------------------------------------------------------------------------
# Approval
# ---------------------------------------------------------------------------
_APPROVABLE_FROM = {
    RecoveryCaseStatus.PENDING.value,
    RecoveryCaseStatus.BLOCKED.value,
}
_IMMUTABLE_FROM = {
    RecoveryCaseStatus.SUCCEEDED.value,
    RecoveryCaseStatus.FAILED.value,
    RecoveryCaseStatus.EXECUTING.value,
    RecoveryCaseStatus.REJECTED.value,
}


@router.post(
    "/recovery/cases/{case_id}/approve",
    response_model=ApprovalResponse,
    status_code=status.HTTP_200_OK,
)
def approve_recovery_case(
    case_id: str,
    session: Session = Depends(get_db),
) -> ApprovalResponse:
    case = CaseLookup.get_case(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="recovery case not found")

    if case.status in _IMMUTABLE_FROM:
        raise HTTPException(
            status_code=409,
            detail=f"case is in state '{case.status}'; cannot approve",
        )
    if case.status == RecoveryCaseStatus.APPROVED.value:
        raise HTTPException(
            status_code=409,
            detail="case already approved",
        )
    if case.status not in _APPROVABLE_FROM:
        # Defensive: any other state we haven't enumerated.
        raise HTTPException(
            status_code=409,
            detail=f"case is in state '{case.status}'; cannot approve",
        )

    approved_at = datetime.now(timezone.utc)
    CaseWriter.update_case(session, case, status=RecoveryCaseStatus.APPROVED.value)
    audit.record(
        session,
        event_type=audit.CASE_APPROVED,
        actor="api_user",
        decision="ACCEPT",
        reason="human approved via API",
        metadata={"case_id": case.id, "approved_at": approved_at.isoformat()},
        recovery_case_id=case.id,
        transaction_id=case.transaction_id,
    )
    session.commit()

    return ApprovalResponse(
        case_id=case.id,
        status="approved",
        approved_at=approved_at,
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def _build_execution_response_from_action(
    *, case_id: str, action: RecoveryAction, idempotency_key: str
) -> ExecutionResponse:
    result = action.result or {}
    external_reference = result.get("external_reference")
    error_code = result.get("error_code")
    amount_paise = int(result.get("amount", 0) or 0)
    status_value = action.status  # SUCCESS / FAILED / SKIPPED

    if status_value == ExecutionStatus.SUCCESS.value:
        out_status = "succeeded"
    elif status_value == ExecutionStatus.SKIPPED.value:
        out_status = "executing"
    else:
        out_status = "failed"

    return ExecutionResponse(
        case_id=case_id,
        status=out_status,
        action_type=action.action_type,
        amount_recovered=amount_paise / 100.0,
        external_reference=external_reference,
        idempotency_key=idempotency_key,
        already_executed=True,
        executed_at=action.executed_at,
        error_code=error_code,
        message=action.reason or "",
    )


@router.post(
    "/recovery/cases/{case_id}/execute",
    response_model=ExecutionResponse,
    status_code=status.HTTP_200_OK,
)
def execute_recovery_case(
    case_id: str,
    session: Session = Depends(get_db),
) -> ExecutionResponse:
    engine = RecoveryEngine.default(session_factory=get_session_factory())
    try:
        result = engine.execute_approved_case(case_id=case_id)
    except CaseNotFound:
        raise HTTPException(status_code=404, detail="recovery case not found")
    except CaseNotEligible as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"case is in state '{exc.current_status}'; "
                "only approved cases can be executed"
            ),
        )

    if isinstance(result, AlreadyExecuted):
        return _build_execution_response_from_action(
            case_id=case_id,
            action=result.action,
            idempotency_key=result.idempotency_key,
        )

    # ProcessResult — fresh execution.
    outcome = result.outcome
    execution = outcome.execution
    if execution is not None and execution.status == ExecutionStatus.SUCCESS:
        out_status: str = "succeeded"
    elif execution is not None and execution.status == ExecutionStatus.SKIPPED:
        out_status = "executing"
    else:
        out_status = "failed"

    idempotency_key = (
        f"case-{outcome.case_id}-action-{execution.action.value}"
        if execution is not None
        else f"case-{outcome.case_id}-noop"
    )
    return ExecutionResponse(
        case_id=outcome.case_id,
        status=out_status,  # type: ignore[arg-type]
        action_type=execution.action.value if execution else None,
        amount_recovered=(
            (execution.amount / 100.0) if execution is not None else 0.0
        ),
        external_reference=(
            execution.external_reference if execution is not None else None
        ),
        idempotency_key=idempotency_key,
        already_executed=False,
        executed_at=execution.executed_at if execution is not None else None,
        error_code=execution.error_code if execution is not None else None,
        message=execution.message if execution is not None else "",
    )


# ---------------------------------------------------------------------------
# Audit timeline
# ---------------------------------------------------------------------------
@router.get("/audit/{case_id}", response_model=list[AuditEventOut])
def get_audit_timeline(
    case_id: str,
    session: Session = Depends(get_db),
) -> list[AuditEventOut]:
    case = CaseLookup.get_case(session, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="recovery case not found")
    rows = (
        session.query(AuditLog)
        .filter(AuditLog.recovery_case_id == case_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    )
    return [AuditEventOut.from_orm_row(row).model_dump(by_alias=True) for row in rows]


__all__ = ["router"]
