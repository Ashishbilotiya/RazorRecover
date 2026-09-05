

from __future__ import annotations

import logging
from typing import Any

from backend.agents.llm import LLMProvider, default_provider
from backend.agents.recovery_agent import (
    deterministic_recovery,
    recommend_recovery,
)
from backend.agents.risk_agent import assess_risk
from backend.agents.root_cause_agent import (
    classify_root_cause,
    deterministic_root_cause,
)
from backend.agents.schemas import (
    AgentPipelineResult,
    RiskAssessment,
    RootCauseAssessment,
    TransactionContext,
)
from backend.ml.inference import (
    ModelNotFoundError,
    RecoveryPrediction,
    predict_recovery,
)

logger = logging.getLogger(__name__)


def _transaction_to_features(ctx: TransactionContext) -> dict[str, Any]:
    """Project the :class:`TransactionContext` into the ML feature schema.

    Numeric features that the context doesn't supply default to safe midpoints
    so the inference call stays well-defined. This is the only place that
    bridges the agent-side context and the ML feature contract.
    """
    return {
        "amount": ctx.amount,
        "customer_transaction_count": 10,  # neutral default
        "customer_success_rate": ctx.customer_success_rate if ctx.customer_success_rate is not None else 0.7,
        "customer_failure_rate": ctx.customer_failure_rate if ctx.customer_failure_rate is not None else 0.1,
        "customer_total_spend": ctx.amount / 100.0 * 5,  # rough proxy
        "average_order_value": ctx.amount / 100.0,
        "previous_retry_count": ctx.previous_retry_count,
        "time_since_last_success": 7,  # neutral default
        "hour_of_day": 14,
        "day_of_week": 3,
        "merchant_success_rate": ctx.merchant_success_rate if ctx.merchant_success_rate is not None else 0.9,
        "payment_method_success_rate": (
            ctx.payment_method_success_rate
            if ctx.payment_method_success_rate is not None
            else 0.9
        ),
        "recent_failure_rate": (
            ctx.customer_failure_rate if ctx.customer_failure_rate is not None else 0.1
        ),
        "payment_method": ctx.payment_method or "card",
        "failure_reason": ctx.failure_reason or "unknown",
    }


def _predict_safely(ctx: TransactionContext) -> RecoveryPrediction:
    """Run ML inference or return a safe neutral fallback if the model is missing."""
    try:
        return predict_recovery(_transaction_to_features(ctx))
    except ModelNotFoundError as exc:
        logger.warning("ML model unavailable (%s); using neutral prediction", exc)
        return RecoveryPrediction(
            recovery_probability=0.5,
            revenue_at_risk=ctx.amount / 100.0 * 0.5,
        )


def run_pipeline(
    *,
    context: TransactionContext,
    provider: LLMProvider | None = None,
) -> AgentPipelineResult:
    """Run ML inference → Risk → Root Cause → Recovery. Never executes."""
    if provider is None:
        provider = default_provider()

    ml_prediction = _predict_safely(context)

    risk = assess_risk(context=context, ml_prediction=ml_prediction, provider=provider)
    root_cause = classify_root_cause(
        context=context, risk=risk, provider=provider
    )
    recommendation = recommend_recovery(
        context=context, risk=risk, root_cause=root_cause, provider=provider
    )

    used_fallback = any(
        src == "fallback"
        for src in (risk.source, root_cause.source, recommendation.source)
    )

    return AgentPipelineResult(
        transaction_id=context.transaction_id,
        risk=risk,
        root_cause=root_cause,
        recommendation=recommendation,
        used_fallback=used_fallback,
    )


def run_pipeline_safely(
    *,
    context: TransactionContext,
    provider: LLMProvider | None = None,
) -> AgentPipelineResult:
    """Outer wrapper that guarantees a structured result, even on programmer error.

    If any agent unexpectedly raises (it shouldn't), this returns a
    conservative RiskAssessment + ESCALATE_TO_HUMAN recommendation rather
    than propagating the exception. The orchestrator must never fail open.
    """
    try:
        return run_pipeline(context=context, provider=provider)
    except Exception as exc:  # noqa: BLE001 — orchestrator must never crash
        logger.exception("Orchestrator pipeline crashed; returning safe default")
        risk = RiskAssessment(
            is_recoverable=False,
            recovery_probability=0.0,
            revenue_at_risk=0.0,
            confidence=0.0,
            reason=f"Pipeline error: {exc.__class__.__name__}",
            source="fallback",
        )
        rc: RootCauseAssessment = deterministic_root_cause(context, risk)
        rec = deterministic_recovery(context, risk, rc)
        return AgentPipelineResult(
            transaction_id=context.transaction_id,
            risk=risk,
            root_cause=rc,
            recommendation=rec,
            used_fallback=True,
        )


__all__ = [
    "AgentPipelineResult",
    "run_pipeline",
    "run_pipeline_safely",
]
