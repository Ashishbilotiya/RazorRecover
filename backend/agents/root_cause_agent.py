"""Root Cause Agent — classifies why the revenue was lost.

The agent picks ONE category from the controlled vocabulary defined in
``backend.agents.schemas.RootCauseCategory``. It
never picks an action, never calls Razorpay, and never invents facts.

If the LLM is unavailable, the deterministic fallback classifies from the
``failure_reason`` and supporting signals using a transparent rule set.
"""

from __future__ import annotations

import logging
from pathlib import Path

from backend.agents.llm import LLMProvider, LLMUnavailable
from backend.agents.schemas import (
    CUSTOMER_FAILURE_REASONS,
    PERMANENT_FAILURE_REASONS,
    RootCauseAssessment,
    RootCauseCategory,
    TEMPORARY_FAILURE_REASONS,
    TransactionContext,
)
from backend.agents.risk_agent import RiskAssessment

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "root_cause_agent.md"


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _format_user_prompt(
    ctx: TransactionContext, risk: RiskAssessment
) -> str:
    return (
        "Classify the root cause of this failed transaction.\n\n"
        f"transaction_id: {ctx.transaction_id}\n"
        f"amount_paise: {ctx.amount}\n"
        f"payment_method: {ctx.payment_method}\n"
        f"failure_reason: {ctx.failure_reason}\n"
        f"customer_id: {ctx.customer_id}\n"
        f"customer_success_rate: {ctx.customer_success_rate}\n"
        f"customer_failure_rate: {ctx.customer_failure_rate}\n"
        f"previous_retry_count: {ctx.previous_retry_count}\n"
        f"merchant_success_rate: {ctx.merchant_success_rate}\n"
        f"payment_method_success_rate: {ctx.payment_method_success_rate}\n"
        f"recovery_probability: {risk.recovery_probability}\n"
    )


def deterministic_root_cause(
    ctx: TransactionContext, _risk: RiskAssessment
) -> RootCauseAssessment:
    """Deterministic classification.

    Order of precedence (matches the prompt's mapping hints):
        1. failure_reason map
        2. payment_method success-rate signal
        3. customer_behavior fallback
        4. unknown
    """
    failure = (ctx.failure_reason or "").lower()
    if failure in TEMPORARY_FAILURE_REASONS:
        if failure == "gateway_degradation":
            return RootCauseAssessment(
                root_cause=RootCauseCategory.GATEWAY_DEGRADATION,
                confidence=0.85,
                reason="Failure reason explicitly indicates gateway-side degradation.",
                source="fallback",
            )
        return RootCauseAssessment(
            root_cause=RootCauseCategory.TEMPORARY_PAYMENT_FAILURE,
            confidence=0.80,
            reason=f"Temporary failure reason '{failure}' suggests a transient issue.",
            source="fallback",
        )

    if failure in PERMANENT_FAILURE_REASONS:
        return RootCauseAssessment(
            root_cause=RootCauseCategory.PERMANENT_PAYMENT_FAILURE,
            confidence=0.85,
            reason=f"Failure reason '{failure}' indicates a permanent decline.",
            source="fallback",
        )

    if failure in CUSTOMER_FAILURE_REASONS:
        return RootCauseAssessment(
            root_cause=RootCauseCategory.CUSTOMER_BEHAVIOR,
            confidence=0.80,
            reason="Customer-initiated cancellation.",
            source="fallback",
        )

    # Method-level signal: if the method success rate is well below the merchant
    # baseline, classify as a payment_method_issue.
    if (
        ctx.payment_method_success_rate is not None
        and ctx.merchant_success_rate is not None
        and ctx.payment_method_success_rate + 0.05 < ctx.merchant_success_rate
    ):
        return RootCauseAssessment(
            root_cause=RootCauseCategory.PAYMENT_METHOD_ISSUE,
            confidence=0.65,
            reason=(
                f"Method success rate {ctx.payment_method_success_rate:.2f} is "
                f"well below merchant baseline {ctx.merchant_success_rate:.2f}."
            ),
            source="fallback",
        )

    return RootCauseAssessment(
        root_cause=RootCauseCategory.UNKNOWN,
        confidence=0.40,
        reason="Insufficient signal to classify confidently.",
        source="fallback",
    )


def classify_root_cause(
    *,
    context: TransactionContext,
    risk: RiskAssessment,
    provider: LLMProvider | None = None,
) -> RootCauseAssessment:
    """Run the Root Cause Agent."""
    fallback = deterministic_root_cause(context, risk)

    if provider is None:
        return fallback

    try:
        assessment = provider.complete_json(
            system=_load_system_prompt(),
            user=_format_user_prompt(context, risk),
            schema=RootCauseAssessment,
        )
    except LLMUnavailable as exc:
        logger.info("Root Cause Agent using fallback (LLM unavailable: %s)", exc)
        return fallback

    return assessment.model_copy(update={"source": "llm"})


__all__ = ["classify_root_cause", "deterministic_root_cause"]
