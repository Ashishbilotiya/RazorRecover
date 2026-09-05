"""Recovery engine — coordinates Agent → Policy → Safeguards → Executor.

This is the only module that wires all four layers together. It owns the
database transaction (one commit per ``process()`` call) and emits the audit
trail. The agent orchestrator only produces a recommendation; the recovery
engine enforces the safety chain.

CLAUDE.md invariants (section 21, 22, 23, 24):

    LLM → Recommendation → Policy Engine → Safeguards → Executor → Razorpay

The engine never lets the agent skip layers. Each layer produces a structured
decision that the next layer consumes; nothing free-form controls downstream
behavior.

Concurrency note: ``process_for_transaction`` opens its own session via the
caller-supplied ``session_factory`` so the engine composes with the API
endpoints' FastAPI dependencies (Phase 5) and the demo scripts (Phase 8) the
same way.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from sqlalchemy.orm import Session

from backend.agents.orchestrator import run_pipeline_safely
from backend.agents.schemas import (
    AgentPipelineResult,
    RecoveryActionType,
    RecoveryRecommendation,
    RiskAssessment,
    RootCauseAssessment,
    RootCauseCategory,
    TransactionContext,
)
from backend.audit import logger as audit
from backend.db.models import Customer, RecoveryCase, Transaction
from backend.db.repository import CaseLookup, CaseWriter
from backend.integrations.razorpay import RazorpayClient, default_client
from backend.recovery.config import RecoveryConfig, load_config
from backend.recovery.executor import execute as execute_action
from backend.recovery.policies import evaluate as evaluate_policy
from backend.recovery.safeguards import (
    check as check_safeguards,
    make_context_provider,
)
from backend.recovery.schemas import (
    ExecutionStatus,
    PolicyDecision,
    PolicyVerdict,
    RecoveryCaseStatus,
    RecoveryOutcome,
    SafeguardDecision,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data classes
# ---------------------------------------------------------------------------
@dataclass
class ProcessResult:
    """What the engine returns to the API/demo."""

    outcome: RecoveryOutcome
    case: RecoveryCase | None


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
@dataclass
class RecoveryEngine:
    """Coordinates the full recovery decision chain."""

    config: RecoveryConfig
    razorpay_client: RazorpayClient
    session_factory: Callable[[], Session]

    @classmethod
    def default(
        cls,
        *,
        session_factory: Callable[[], Session],
        razorpay_client: RazorpayClient | None = None,
        config: RecoveryConfig | None = None,
    ) -> "RecoveryEngine":
        return cls(
            config=config or load_config(),
            razorpay_client=razorpay_client or default_client(),
            session_factory=session_factory,
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    def process_for_transaction(
        self,
        *,
        transaction: Transaction,
        customer: Customer | None,
        context: TransactionContext,
    ) -> ProcessResult:
        """Run the full pipeline for a single transaction.

        Order of operations:

        1.  Run agent pipeline (no side effects).
        2.  Persist a recovery case in ``pending`` state.
        3.  Run policy engine → ``PolicyDecision``.
        4.  If approved, run safeguards gate → ``SafeguardDecision``.
        5.  If allowed, invoke the executor (which talks to Razorpay).
        6.  Persist a ``RecoveryAction`` row + outcome audit + final case state.
        7.  Commit the surrounding DB transaction.
        """
        session = self.session_factory()
        try:
            return self._run_in_session(
                session=session,
                transaction=transaction,
                customer=customer,
                context=context,
            )
        finally:
            session.close()

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------
    def _run_in_session(
        self,
        *,
        session: Session,
        transaction: Transaction,
        customer: Customer | None,
        context: TransactionContext,
    ) -> ProcessResult:
        pipeline = run_pipeline_safely(context=context)
        payment_succeeded = _payment_already_succeeded(transaction)

        case = self._upsert_pending_case(
            session=session,
            transaction=transaction,
            customer=customer,
            pipeline=pipeline,
        )

        policy = evaluate_policy(
            recommendation=pipeline.recommendation,
            risk=pipeline.risk,
            context=context,
            config=self.config,
            payment_already_succeeded=payment_succeeded,
        )
        self._audit_policy(session=session, case=case, policy=policy)

        # Persist the policy verdict immediately so the case state reflects
        # what was decided even if the executor never runs.
        case_status = _case_status_for_policy(policy)
        CaseWriter.update_case(
            session, case, status=case_status.value, amount_recovered=0.0
        )

        safeguard, execution = self._maybe_execute(
            session=session,
            case=case,
            recommendation=pipeline.recommendation,
            risk=pipeline.risk,
            policy=policy,
            context=context,
            transaction=transaction,
            override_human_review=False,
        )

        outcome = self._finalize(
            session=session,
            case=case,
            pipeline=pipeline,
            policy=policy,
            safeguard=safeguard,
            execution=execution,
        )

        session.commit()
        # Refresh and expunge the case so it remains usable after the session closes.
        session.refresh(case)
        session.expunge(case)
        return ProcessResult(outcome=outcome, case=case)

    # ------------------------------------------------------------------
    # Stage: case persistence
    # ------------------------------------------------------------------
    def _upsert_pending_case(
        self,
        *,
        session: Session,
        transaction: Transaction,
        customer: Customer | None,
        pipeline: AgentPipelineResult,
    ) -> RecoveryCase:
        existing = CaseLookup.get_case_by_transaction(session, transaction.id)
        if existing is not None:
            return existing

        revenue_at_risk = (
            transaction.amount * pipeline.risk.recovery_probability
        ) / 100.0  # paise → rupees for display

        case = CaseWriter.create_case(
            session,
            transaction=transaction,
            customer=customer,
            amount=transaction.amount / 100.0,
            revenue_at_risk=revenue_at_risk,
            recovery_probability=pipeline.risk.recovery_probability,
            root_cause=pipeline.root_cause.root_cause.value,
            recommended_action=pipeline.recommendation.action.value,
            confidence=pipeline.risk.confidence,
            status=RecoveryCaseStatus.PENDING.value,
        )
        audit.record(
            session,
            event_type=audit.RECOVERY_CASE_CREATED,
            actor="recovery_engine",
            decision="case_created",
            reason=pipeline.recommendation.reason[:500],
            metadata={
                "transaction_id": transaction.id,
                "amount": transaction.amount,
                "root_cause": pipeline.root_cause.root_cause.value,
                "agent_action": pipeline.recommendation.action.value,
                "agent_confidence": pipeline.recommendation.confidence,
                "recovery_probability": pipeline.risk.recovery_probability,
                "revenue_at_risk": revenue_at_risk,
            },
            recovery_case_id=case.id,
            transaction_id=transaction.id,
        )
        return case

    # ------------------------------------------------------------------
    # Stage: safeguards + execution
    # ------------------------------------------------------------------
    def _maybe_execute(
        self,
        *,
        session: Session,
        case: RecoveryCase,
        recommendation: RecoveryRecommendation,
        risk: RiskAssessment,
        policy: PolicyDecision,
        context: TransactionContext,
        transaction: Transaction,
        override_human_review: bool = False,
    ) -> tuple[SafeguardDecision, Any]:
        """Return the safeguard decision (always) and execution result (sometimes).

        If ``override_human_review`` is True, we use the agent's recommendation
        even if the policy engine requested human review.
        """
        action = policy.action
        if override_human_review and policy.verdict == PolicyVerdict.HUMAN_REVIEW:
            action = recommendation.action
            # Temporarily override policy approval for the safeguards check.
            # We create a new PolicyDecision to avoid mutating the original.
            policy = PolicyDecision(
                approved=True,
                verdict=PolicyVerdict.APPROVED,
                action=action,
                policy_rule=policy.policy_rule,
                reason=f"Manually approved override: {policy.reason}",
                required_safeguards=policy.required_safeguards,
                thresholds=policy.thresholds,
            )

        idempotency_key = self._build_idempotency_key(case=case, action=action)

        prior_success = sum(
            1
            for a in CaseLookup.actions_for_case(session, case.id)
            if a.status == ExecutionStatus.SUCCESS.value
        )
        prior_with_key = (
            CaseWriter.idempotent_existing(
                session,
                case_id=case.id,
                idempotency_key=idempotency_key,
            )
            is not None
        )

        provider = make_context_provider(
            payment_already_succeeded=_payment_already_succeeded(transaction),
            prior_success_action_count=prior_success,
            action_already_seen_with_key=prior_with_key,
        )
        safeguard = check_safeguards(
            recommendation=recommendation,
            risk=risk,
            context=context,
            config=self.config,
            policy=policy,
            idempotency_key=idempotency_key,
            lookup=provider,
            override_human_review=override_human_review,
        )
        self._audit_safeguard(
            session=session,
            case=case,
            policy=policy,
            safeguard=safeguard,
        )

        execution = None
        if safeguard.allowed and action is not None:
            CaseWriter.update_case(
                session, case, status=RecoveryCaseStatus.EXECUTING.value
            )
            execution = execute_action(
                action=action,
                razorpay_order_id=context.razorpay_order_id or transaction.razorpay_order_id,
                razorpay_payment_id=context.razorpay_payment_id or transaction.razorpay_payment_id,
                amount=transaction.amount,
                currency=transaction.currency or "INR",
                idempotency_key=idempotency_key,
                client=self.razorpay_client,
                metadata={
                    "transaction_id": transaction.id,
                    "case_id": case.id,
                    "policy_rule": policy.policy_rule.value,
                },
            )
            self._audit_execution(
                session=session,
                case=case,
                execution=execution,
                idempotency_key=idempotency_key,
            )
        else:
            self._audit_blocked(
                session=session,
                case=case,
                policy=policy,
                safeguard=safeguard,
            )

        return safeguard, execution

    # ------------------------------------------------------------------
    # Stage: finalize + outcome
    # ------------------------------------------------------------------
    def _finalize(
        self,
        *,
        session: Session,
        case: RecoveryCase,
        pipeline: AgentPipelineResult,
        policy: PolicyDecision,
        safeguard: SafeguardDecision,
        execution: Any,
    ) -> RecoveryOutcome:
        amount_recovered = 0.0
        final_status = RecoveryCaseStatus.PENDING

        if execution is not None:
            if execution.success and execution.status == ExecutionStatus.SUCCESS:
                amount_recovered = (execution.amount or 0) / 100.0
                final_status = RecoveryCaseStatus.SUCCEEDED
            else:
                final_status = RecoveryCaseStatus.FAILED
        elif policy.verdict == PolicyVerdict.REJECTED:
            final_status = RecoveryCaseStatus.REJECTED
        elif policy.verdict == PolicyVerdict.HUMAN_REVIEW:
            final_status = RecoveryCaseStatus.BLOCKED
        elif not safeguard.allowed:
            final_status = RecoveryCaseStatus.BLOCKED

        CaseWriter.update_case(
            session, case, status=final_status.value, amount_recovered=amount_recovered
        )

        blocked_reason = (
            safeguard.reason if not safeguard.allowed and execution is None
            else None
        )

        audit.record(
            session,
            event_type=audit.OUTCOME_RECORDED,
            actor="recovery_engine",
            decision=final_status.value,
            reason=blocked_reason or "Recovery completed.",
            metadata={
                "amount_recovered": amount_recovered,
                "policy_verdict": policy.verdict.value,
                "policy_rule": policy.policy_rule.value,
                "safeguard_allowed": safeguard.allowed,
                "execution_status": execution.status.value if execution else None,
            },
            recovery_case_id=case.id,
            transaction_id=case.transaction_id,
        )

        return RecoveryOutcome(
            case_id=case.id,
            transaction_id=pipeline.transaction_id,
            recommendation=pipeline.recommendation,
            policy=policy,
            safeguard=safeguard,
            execution=execution,
            case_status=final_status,
            blocked_reason=blocked_reason,
            created_at=datetime.now(timezone.utc),
        )

    # ------------------------------------------------------------------
    # Audit helpers
    # ------------------------------------------------------------------
    def _audit_policy(
        self,
        *,
        session: Session,
        case: RecoveryCase,
        policy: PolicyDecision,
    ) -> None:
        audit.record(
            session,
            event_type=audit.POLICY_DECISION,
            actor="policy_engine",
            decision=policy.verdict.value,
            reason=policy.reason,
            metadata={
                "approved": policy.approved,
                "policy_rule": policy.policy_rule.value,
                "action": policy.action.value if policy.action else None,
                "required_safeguards": list(policy.required_safeguards),
                "thresholds": {k: float(v) for k, v in policy.thresholds.items()},
            },
            recovery_case_id=case.id,
            transaction_id=case.transaction_id,
        )

    def _audit_safeguard(
        self,
        *,
        session: Session,
        case: RecoveryCase,
        policy: PolicyDecision,
        safeguard: SafeguardDecision,
    ) -> None:
        audit.record(
            session,
            event_type=audit.SAFEGUARD_DECISION,
            actor="safeguards",
            decision=("allowed" if safeguard.allowed else "blocked"),
            reason=safeguard.reason,
            metadata={
                "failed_safeguard": (
                    safeguard.failed_safeguard.value
                    if safeguard.failed_safeguard
                    else None
                ),
                "policy_rule": policy.policy_rule.value,
                "details": dict(safeguard.details),
            },
            recovery_case_id=case.id,
            transaction_id=case.transaction_id,
        )

    def _audit_execution(
        self,
        *,
        session: Session,
        case: RecoveryCase,
        execution: Any,
        idempotency_key: str,
    ) -> None:
        CaseWriter.record_action(
            session,
            case=case,
            action_type=execution.action.value,
            status=execution.status.value,
            reason=execution.message,
            attempt_number=1,
            executed_at=execution.executed_at,
            result={
                "external_reference": execution.external_reference,
                "error_code": execution.error_code,
                "amount": execution.amount,
                "idempotency_key": idempotency_key,
            },
        )
        audit.record(
            session,
            event_type=(
                audit.EXECUTION_SUCCEEDED
                if execution.success
                else audit.EXECUTION_FAILED
            ),
            actor="executor",
            decision=execution.status.value,
            reason=execution.message,
            metadata={
                "action": execution.action.value,
                "external_reference": execution.external_reference,
                "error_code": execution.error_code,
                "idempotency_key": idempotency_key,
            },
            recovery_case_id=case.id,
            transaction_id=case.transaction_id,
        )

    def _audit_blocked(
        self,
        *,
        session: Session,
        case: RecoveryCase,
        policy: PolicyDecision,
        safeguard: SafeguardDecision,
    ) -> None:
        audit.record(
            session,
            event_type=audit.EXECUTION_BLOCKED,
            actor="safeguards",
            decision="blocked",
            reason=safeguard.reason,
            metadata={
                "policy_rule": policy.policy_rule.value,
                "failed_safeguard": (
                    safeguard.failed_safeguard.value
                    if safeguard.failed_safeguard
                    else None
                ),
            },
            recovery_case_id=case.id,
            transaction_id=case.transaction_id,
        )

    # ------------------------------------------------------------------
    # Idempotency key
    # ------------------------------------------------------------------
    @staticmethod
    def _build_idempotency_key(
        *, case: RecoveryCase, action: RecoveryActionType | None
    ) -> str:
        if action is None:
            return f"case-{case.id}-noop"
        return f"case-{case.id}-action-{action.value}"

    # ------------------------------------------------------------------
    # API execution path (Phase 5)
    # ------------------------------------------------------------------
    def execute_approved_case(self, *, case_id: str) -> "ProcessResult | _AlreadyExecuted":
        """Execute a previously approved recovery case.

        Used by ``POST /api/recovery/cases/{case_id}/execute``. Differs from
        :meth:`process_for_transaction` in two ways:

        1. The agent pipeline is **not** re-run. The :class:`TransactionContext`,
           :class:`RiskAssessment`, and :class:`RecoveryRecommendation` are
           reconstructed from the **stored** fields of the case + transaction.
           This is intentional — we never let the API silently re-invoke an LLM
           at execute time.
        2. The case must already be in the :attr:`RecoveryCaseStatus.APPROVED`
           state. Anything else raises :class:`CaseNotEligible` for the
           handler to map to a 409.

        Returns either a :class:`ProcessResult` (a fresh execution) or a
        :class:`_AlreadyExecuted` sentinel wrapping the prior ``RecoveryAction``
        so the handler can return the cached ``ExecutionResponse`` without
        re-calling Razorpay.

        Order of operations:

        1. Load ``RecoveryCase`` + ``Transaction`` + optional ``Customer``.
        2. Build idempotency key, then probe
           :meth:`CaseWriter.idempotent_existing`. If hit → return
           :class:`_AlreadyExecuted` (no DB writes, no Razorpay).
        3. Reconstruct ``TransactionContext`` from the ORM row.
        4. Reconstruct ``RiskAssessment`` + ``RecoveryRecommendation`` from
           stored case fields (verbatim — no LLM).
        5. Re-run **policy** (deterministic).
        6. Re-run **safeguards** (deterministic).
        7. Call **executor** (the only module that calls Razorpay).
        8. Persist action + outcome + audit; commit.
        """
        session = self.session_factory()
        try:
            case = CaseLookup.get_case(session, case_id)
            if case is None:
                raise CaseNotFound(case_id)

            transaction = (
                session.get(Transaction, case.transaction_id)
                if case.transaction_id
                else None
            )
            if transaction is None:
                raise CaseNotFound(case_id)

            customer = (
                session.get(Customer, case.customer_id)
                if case.customer_id
                else None
            )

            # 1. Idempotency replay protection.
            try:
                action_enum = RecoveryActionType(case.recommended_action)
            except ValueError as exc:
                raise CaseNotFound(case_id) from exc

            idempotency_key = self._build_idempotency_key(
                case=case, action=action_enum
            )
            prior = CaseWriter.idempotent_existing(
                session, case_id=case.id, idempotency_key=idempotency_key
            )
            if prior is not None:
                return _AlreadyExecuted(action=prior, idempotency_key=idempotency_key)

            # 2. State guard — only APPROVED is executable.
            if case.status != RecoveryCaseStatus.APPROVED.value:
                raise CaseNotEligible(
                    case_id=case_id, current_status=case.status
                )

            # 3. Reconstruct inputs deterministically from stored rows.
            context = _build_context_from_transaction(transaction, customer)
            risk = _reconstruct_risk_from_case(case)
            recommendation = _reconstruct_recommendation_from_case(case)
            payment_succeeded = _payment_already_succeeded(transaction)

            # 4. Re-run policy + safeguards + executor (no LLM re-call).
            policy = evaluate_policy(
                recommendation=recommendation,
                risk=risk,
                context=context,
                config=self.config,
                payment_already_succeeded=payment_succeeded,
            )
            self._audit_policy(session=session, case=case, policy=policy)

            safeguard, execution = self._maybe_execute(
                session=session,
                case=case,
                recommendation=recommendation,
                risk=risk,
                policy=policy,
                context=context,
                transaction=transaction,
                override_human_review=True,
            )

            outcome = self._finalize(
                session=session,
                case=case,
                pipeline=AgentPipelineResult(
                    transaction_id=case.transaction_id or "",
                    risk=risk,
                    root_cause=_reconstruct_root_cause_from_case(case),
                    recommendation=recommendation,
                    used_fallback=False,
                ),
                policy=policy,
                safeguard=safeguard,
                execution=execution,
            )
            session.commit()
            return ProcessResult(outcome=outcome, case=case)
        finally:
            session.close()


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def _payment_already_succeeded(transaction: Transaction) -> bool:
    return (transaction.status or "").lower() == "captured"


def _case_status_for_policy(policy: PolicyDecision) -> RecoveryCaseStatus:
    if policy.verdict == PolicyVerdict.APPROVED:
        return RecoveryCaseStatus.APPROVED
    if policy.verdict == PolicyVerdict.HUMAN_REVIEW:
        return RecoveryCaseStatus.BLOCKED
    return RecoveryCaseStatus.REJECTED


def _build_context_from_transaction(
    transaction: Transaction, customer: Customer | None
) -> TransactionContext:
    """Build a :class:`TransactionContext` from the ORM rows.

    Used by both the webhook → pipeline trigger and the API execution path
    so the two paths agree on what the agent sees. Amount comes from the
    transaction in paise; success-rate defaults are filled from the customer
    row when present.
    """
    success_rate = (
        (customer.successful_transactions / customer.total_transactions)
        if customer and customer.total_transactions
        else None
    )
    failure_rate = (
        (customer.failed_transactions / customer.total_transactions)
        if customer and customer.total_transactions
        else None
    )
    return TransactionContext(
        transaction_id=transaction.id,
        amount=transaction.amount,
        currency=transaction.currency or "INR",
        payment_method=transaction.payment_method,
        failure_reason=transaction.failure_reason,
        customer_id=customer.id if customer else None,
        customer_success_rate=success_rate,
        customer_failure_rate=failure_rate,
        previous_retry_count=0,
        merchant_success_rate=None,
        payment_method_success_rate=None,
        razorpay_order_id=transaction.razorpay_order_id,
        razorpay_payment_id=transaction.razorpay_payment_id,
    )


def _reconstruct_risk_from_case(case: RecoveryCase) -> RiskAssessment:
    return RiskAssessment(
        is_recoverable=case.status
        not in (
            RecoveryCaseStatus.REJECTED.value,
            RecoveryCaseStatus.BLOCKED.value,
        ),
        recovery_probability=case.recovery_probability,
        revenue_at_risk=case.revenue_at_risk,
        confidence=case.confidence,
        reason="reconstructed_from_persisted_case",
        source="ml",
    )


def _reconstruct_recommendation_from_case(
    case: RecoveryCase,
) -> RecoveryRecommendation:
    try:
        action = RecoveryActionType(case.recommended_action or "")
    except ValueError:
        action = RecoveryActionType.STOP
    return RecoveryRecommendation(
        action=action,
        confidence=case.confidence,
        reason="reconstructed_from_persisted_case",
        expected_recovery=case.revenue_at_risk,
        source="fallback",
    )


def _reconstruct_root_cause_from_case(case: RecoveryCase) -> RootCauseAssessment:
    try:
        category = RootCauseCategory(case.root_cause or "")
    except ValueError:
        category = RootCauseCategory.UNKNOWN
    return RootCauseAssessment(
        root_cause=category,
        confidence=case.confidence,
        reason="reconstructed_from_persisted_case",
        source="fallback",
    )


# ---------------------------------------------------------------------------
# API-facing errors and idempotency sentinel
# ---------------------------------------------------------------------------
class CaseNotFound(LookupError):
    """Raised by :meth:`RecoveryEngine.execute_approved_case` when the case id is unknown."""

    def __init__(self, case_id: str) -> None:
        super().__init__(case_id)
        self.case_id = case_id


class CaseNotEligible(Exception):
    """Raised when the case exists but is in a state that cannot be executed."""

    def __init__(self, *, case_id: str, current_status: str) -> None:
        super().__init__(
            f"case {case_id} is in state {current_status}; cannot execute"
        )
        self.case_id = case_id
        self.current_status = current_status


@dataclass(frozen=True)
class _AlreadyExecuted:
    """Sentinel returned by ``execute_approved_case`` on a successful replay.

    Wraps the persisted :class:`RecoveryAction` row and the idempotency key so
    the API handler can return the cached ``ExecutionResponse`` without
    re-running policy, safeguards, or executor (no Razorpay call).
    """

    action: Any  # RecoveryAction row (typed loosely to avoid circular imports)
    idempotency_key: str


# Public alias — what the handler sees.
AlreadyExecuted = _AlreadyExecuted


__all__ = [
    "AlreadyExecuted",
    "CaseNotEligible",
    "CaseNotFound",
    "ProcessResult",
    "RecoveryEngine",
]
