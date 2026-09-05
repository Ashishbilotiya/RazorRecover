

from __future__ import annotations

import logging
from pathlib import Path

from backend.agents.llm import LLMProvider, LLMUnavailable
from backend.agents.schemas import (
    RecoveryActionType,
    RecoveryRecommendation,
    RiskAssessment,
    RootCauseAssessment,
    RootCauseCategory,
    TransactionContext,
)

logger = logging.getLogger(__name__)

PROMPT_PATH = Path(__file__).parent / "prompts" / "recovery_agent.md"

# Threshold below which we refuse to recommend a money-moving action.
MIN_PROBABILITY_FOR_ACTION = 0.50


def _load_system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _format_user_prompt(
    ctx: TransactionContext,
    risk: RiskAssessment,
    root_cause: RootCauseAssessment,
) -> str:
    return (
        "Recommend ONE recovery action.\n\n"
        f"transaction_id: {ctx.transaction_id}\n"
        f"amount_paise: {ctx.amount}\n"
        f"payment_method: {ctx.payment_method}\n"
        f"failure_reason: {ctx.failure_reason}\n"
        f"customer_success_rate: {ctx.customer_success_rate}\n"
        f"customer_failure_rate: {ctx.customer_failure_rate}\n"
        f"previous_retry_count: {ctx.previous_retry_count}\n"
        f"recovery_probability: {risk.recovery_probability}\n"
        f"revenue_at_risk: {risk.revenue_at_risk}\n"
        f"root_cause: {root_cause.root_cause.value} ({root_cause.confidence:.2f})\n"
    )


def deterministic_recovery(
    ctx: TransactionContext,
    risk: RiskAssessment,
    root_cause: RootCauseAssessment,
) -> RecoveryRecommendation:
    failure = (ctx.failure_reason or "").lower()
    prob = risk.recovery_probability
    customer_success = ctx.customer_success_rate or 0.5

    # Stop / escalate early for unrecoverable cases.
    if not risk.is_recoverable or prob < MIN_PROBABILITY_FOR_ACTION:
        return RecoveryRecommendation(
            action=RecoveryActionType.ESCALATE_TO_HUMAN,
            confidence=0.75,
            reason=(
                f"Recovery probability {prob:.2f} is too low to act on; "
                "escalate for human review."
            ),
            expected_recovery=risk.revenue_at_risk,
            source="fallback",
        )

    # High-value, retry-safe, temporary failure → RETRY_PAYMENT.
    # Threshold matches MIN_PROBABILITY_FOR_ACTION so the deterministic
    # recommendation stays aligned with the policy-engine gate.
    if (
        failure in {"temporary_timeout", "network_error"}
        and prob >= MIN_PROBABILITY_FOR_ACTION
        and ctx.previous_retry_count < 3
    ):
        return RecoveryRecommendation(
            action=RecoveryActionType.RETRY_PAYMENT,
            confidence=min(0.95, prob),
            reason=(
                "Temporary failure with high recovery probability and "
                "no previous retry attempt."
            ),
            expected_recovery=risk.revenue_at_risk,
            source="fallback",
        )

    # Permanent decline + decent customer → suggest alternate method.
    if failure in {"card_declined", "insufficient_funds", "authentication_failed"}:
        return RecoveryRecommendation(
            action=RecoveryActionType.SUGGEST_ALTERNATE_PAYMENT_METHOD,
            confidence=min(0.85, prob + 0.1),
            reason=(
                f"Permanent decline reason '{failure}'; alternate method is "
                "more likely to succeed than a retry."
            ),
            expected_recovery=risk.revenue_at_risk,
            source="fallback",
        )

    # High-value, good customer, low retry count → payment link.
    if ctx.amount >= 50_000 and customer_success >= 0.7 and ctx.previous_retry_count == 0:
        return RecoveryRecommendation(
            action=RecoveryActionType.SEND_PAYMENT_LINK,
            confidence=min(0.85, prob),
            reason=(
                "High-value transaction with a good customer and no prior retry; "
                "a payment link is more convenient than a forced retry."
            ),
            expected_recovery=risk.revenue_at_risk,
            source="fallback",
        )

    # Customer-initiated → reminder.
    if root_cause.root_cause == RootCauseCategory.CUSTOMER_BEHAVIOR:
        return RecoveryRecommendation(
            action=RecoveryActionType.SEND_REMINDER,
            confidence=0.60,
            reason="Customer-initiated event; a low-friction reminder is appropriate.",
            expected_recovery=risk.revenue_at_risk * 0.5,
            source="fallback",
        )

    # Gateway degradation → checkout recovery nudge.
    if root_cause.root_cause == RootCauseCategory.GATEWAY_DEGRADATION:
        return RecoveryRecommendation(
            action=RecoveryActionType.CHECKOUT_RECOVERY,
            confidence=0.65,
            reason="Gateway-side issue; an alternate checkout path may help.",
            expected_recovery=risk.revenue_at_risk,
            source="fallback",
        )

    # Default: don't move money.
    return RecoveryRecommendation(
        action=RecoveryActionType.STOP,
        confidence=0.50,
        reason="Insufficient signal to recommend a recovery action.",
        expected_recovery=0.0,
        source="fallback",
    )


def recommend_recovery(
    *,
    context: TransactionContext,
    risk: RiskAssessment,
    root_cause: RootCauseAssessment,
    provider: LLMProvider | None = None,
) -> RecoveryRecommendation:
    """Run the Recovery Agent."""
    fallback = deterministic_recovery(context, risk, root_cause)

    if provider is None:
        return fallback

    try:
        rec = provider.complete_json(
            system=_load_system_prompt(),
            user=_format_user_prompt(context, risk, root_cause),
            schema=RecoveryRecommendation,
        )
    except LLMUnavailable as exc:
        logger.info("Recovery Agent using fallback (LLM unavailable: %s)", exc)
        return fallback

    return rec.model_copy(update={"source": "llm"})


__all__ = ["recommend_recovery", "deterministic_recovery", "MIN_PROBABILITY_FOR_ACTION"]
