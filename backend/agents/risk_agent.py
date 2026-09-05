"""Risk Agent — decides if a failed transaction is worth recovering.

Pipeline:
    ML inference (recovery_probability, revenue_at_risk)
          ↓
    Risk Agent (LLM optional, deterministic fallback mandatory)
          ↓
    RiskAssessment

The agent:
  - treats the ML signal as authoritative for `recovery_probability` and
    `revenue_at_risk` (it never invents its own probability);
  - may adjust the *confidence* in that probability based on business context;
  - writes a short business reason;
  - never calls Razorpay or selects an action.

If the LLM fails for any reason, the deterministic fallback produces an
identical-schema RiskAssessment so the orchestrator never has to handle a
text exception.

See CLAUDE.md sections 16, 20, 21, 41.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.agents.llm import LLMProvider, LLMUnavailable
from backend.agents.schemas import RiskAssessment, TransactionContext
from backend.ml.inference import RecoveryPrediction

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "risk_agent.md"


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _format_user_prompt(ctx: TransactionContext, ml: RecoveryPrediction) -> str:
    return (
        "Analyze this failed transaction and produce the required JSON.\n\n"
        f"transaction_id: {ctx.transaction_id}\n"
        f"amount_paise: {ctx.amount}\n"
        f"payment_method: {ctx.payment_method}\n"
        f"failure_reason: {ctx.failure_reason}\n"
        f"customer_id: {ctx.customer_id}\n"
        f"customer_success_rate: {ctx.customer_success_rate}\n"
        f"customer_failure_rate: {ctx.customer_failure_rate}\n"
        f"previous_retry_count: {ctx.previous_retry_count}\n"
        f"merchant_success_rate: {ctx.merchant_success_rate}\n"
        f"payment_method_success_rate: {ctx.payment_method_success_rate}\n\n"
        "ML output (authoritative):\n"
        f"recovery_probability: {ml.recovery_probability}\n"
        f"revenue_at_risk_inr: {ml.revenue_at_risk}\n"
    )


def deterministic_risk(
    ctx: TransactionContext, ml: RecoveryPrediction
) -> RiskAssessment:
    """Compute the fallback RiskAssessment.

    Confidence starts at the ML probability, dampened slightly when the
    customer signal is thin (low customer success rate) or the merchant is
    performing poorly.
    """
    prob = ml.recovery_probability
    revenue = ml.revenue_at_risk

    customer_signal = ctx.customer_success_rate if ctx.customer_success_rate is not None else 0.5
    method_signal = (
        ctx.payment_method_success_rate
        if ctx.payment_method_success_rate is not None
        else 0.5
    )
    merchant_signal = ctx.merchant_success_rate if ctx.merchant_success_rate is not None else 0.9

    # Confidence: weighted blend of probability and signal quality.
    signal = 0.5 * customer_signal + 0.3 * method_signal + 0.2 * merchant_signal
    confidence = max(0.0, min(1.0, 0.4 * prob + 0.6 * signal))

    is_recoverable = prob >= 0.5

    if is_recoverable:
        reason = (
            f"ML probability {prob:.2f} with customer success {customer_signal:.2f}; "
            "case is worth pursuing."
        )
    else:
        reason = (
            f"ML probability {prob:.2f} is below the 0.5 threshold; "
            "not worth pursuing."
        )

    return RiskAssessment(
        is_recoverable=is_recoverable,
        recovery_probability=prob,
        revenue_at_risk=revenue,
        confidence=confidence,
        reason=reason,
        source="ml",
    )


def assess_risk(
    *,
    context: TransactionContext,
    ml_prediction: RecoveryPrediction,
    provider: LLMProvider | None = None,
) -> RiskAssessment:
    """Run the Risk Agent.

    Returns a deterministic fallback when ``provider`` is None, when the
    provider has nothing queued, or when the LLM call fails.
    """
    fallback = deterministic_risk(context, ml_prediction)

    if provider is None:
        return fallback

    try:
        assessment = provider.complete_json(
            system=_load_system_prompt(),
            user=_format_user_prompt(context, ml_prediction),
            schema=RiskAssessment,
        )
    except LLMUnavailable as exc:
        logger.info("Risk Agent using fallback (LLM unavailable: %s)", exc)
        return fallback

    # Validate the LLM output: probability and revenue must mirror the ML
    # signal. If the LLM tried to override them, clamp + fall back rather than
    # propagate a hallucinated number.
    if (
        abs(assessment.recovery_probability - ml_prediction.recovery_probability) > 1e-3
        or abs(assessment.revenue_at_risk - ml_prediction.revenue_at_risk) > 1e-3
    ):
        logger.warning(
            "Risk Agent LLM overrode ML signal (prob %.3f→%.3f, rev %.3f→%.3f); using fallback",
            ml_prediction.recovery_probability,
            assessment.recovery_probability,
            ml_prediction.revenue_at_risk,
            assessment.revenue_at_risk,
        )
        return fallback

    return assessment.model_copy(update={"source": "llm"})


__all__ = ["assess_risk", "deterministic_risk"]