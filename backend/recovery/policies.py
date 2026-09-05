"""Policy engine — deterministic rules (CLAUDE.md section 22).

Policies never depend on LLM interpretation. They receive the structured
:class:`RecoveryRecommendation` and the :class:`TransactionContext`, plus the
shared :class:`RecoveryConfig`, and return a deterministic
:class:`PolicyDecision`.

Rules (precedence order):

1. ``STOP`` or ``payment already succeeded`` → REJECT / no-op.
2. ``ESCALATE_TO_HUMAN`` is honored verbatim.
3. Action not in the configured ``enabled_actions`` → REJECT.
4. ``RETRY_PAYMENT`` rules:
     - failure_reason in {temporary_timeout, network_error}
     - recovery_probability >= confidence_threshold
     - previous_retry_count < retry_limit
5. ``SUGGEST_ALTERNATE_PAYMENT_METHOD`` rules:
     - failure_reason in permanent set
     - probability >= confidence_threshold
6. ``SEND_PAYMENT_LINK`` rules:
     - amount >= amount_escalation_limit
     - previous_retry_count == 0
7. ``SEND_REMINDER`` rules:
     - customer-initiated failure
     - probability >= 0.5
8. ``CHECKOUT_RECOVERY`` rules:
     - gateway degradation root cause
9. Anything above :attr:`RecoveryConfig.max_payment_amount` → HUMAN_REVIEW.
"""

from __future__ import annotations

import logging
from typing import Iterable

from backend.agents.schemas import (
    CUSTOMER_FAILURE_REASONS,
    PERMANENT_FAILURE_REASONS,
    RecoveryActionType,
    RecoveryRecommendation,
    RiskAssessment,
    TEMPORARY_FAILURE_REASONS,
    TransactionContext,
)
from backend.recovery.config import RecoveryConfig
from backend.recovery.schemas import (
    PolicyDecision,
    PolicyRule,
    PolicyVerdict,
)

logger = logging.getLogger(__name__)


# Failure reasons that should never trigger a retry.
NON_RETRYABLE_REASONS = frozenset(
    PERMANENT_FAILURE_REASONS | {"user_cancelled"} | {"unknown"}
)


def evaluate(
    *,
    recommendation: RecoveryRecommendation,
    risk: RiskAssessment,
    context: TransactionContext,
    config: RecoveryConfig,
    payment_already_succeeded: bool = False,
) -> PolicyDecision:
    """Compute a policy verdict for a single recovery recommendation.

    The recovery probability is sourced from the structured ``RiskAssessment``
    (which is itself fed by ML) — never from the LLM-only recommendation —
    so the safety gate cannot be tricked by hallucinated probabilities.
    """
    failure = (context.failure_reason or "").lower()
    amount = context.amount
    prob = risk.recovery_probability
    action = recommendation.action

    # Rule 1 — payment already succeeded → stop.
    if payment_already_succeeded:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.REJECTED,
            action=None,
            policy_rule=PolicyRule.PAYMENT_ALREADY_SUCCEEDED,
            reason="Payment already succeeded; no recovery needed.",
            required_safeguards=[],
            thresholds={"payment_already_succeeded": 1.0},
        )

    # Rule 2 — STOP recommendation: honor but mark rejected.
    if action == RecoveryActionType.STOP:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.REJECTED,
            action=None,
            policy_rule=PolicyRule.NO_ACTION_NEEDED,
            reason="Agent recommended STOP; nothing to do.",
            required_safeguards=[],
            thresholds={"recommendation": 0.0},
        )

    # Rule 3 — Action not in the configured allow-list.
    if action.value not in config.enabled_actions:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.REJECTED,
            action=None,
            policy_rule=PolicyRule.ACTION_NOT_PERMITTED,
            reason=f"Action {action.value} is not in the configured allow-list.",
            required_safeguards=[],
            thresholds={"enabled_actions": float(len(config.enabled_actions))},
        )

    # Rule 4 — RETRY_PAYMENT.
    if action == RecoveryActionType.RETRY_PAYMENT:
        return _retry_policy(
            recommendation=recommendation,
            context=context,
            config=config,
            failure=failure,
            prob=prob,
            amount=amount,
        )

    # Rule 5 — SUGGEST_ALTERNATE_PAYMENT_METHOD.
    if action == RecoveryActionType.SUGGEST_ALTERNATE_PAYMENT_METHOD:
        return _alternate_policy(
            recommendation=recommendation,
            context=context,
            config=config,
            failure=failure,
            prob=prob,
            amount=amount,
        )

    # Rule 6 — SEND_PAYMENT_LINK.
    if action == RecoveryActionType.SEND_PAYMENT_LINK:
        return _payment_link_policy(
            recommendation=recommendation,
            context=context,
            config=config,
            failure=failure,
            prob=prob,
            amount=amount,
        )

    # Rule 7 — SEND_REMINDER.
    if action == RecoveryActionType.SEND_REMINDER:
        return _reminder_policy(
            recommendation=recommendation,
            context=context,
            config=config,
            failure=failure,
            prob=prob,
            amount=amount,
        )

    # Rule 8 — CHECKOUT_RECOVERY.
    if action == RecoveryActionType.CHECKOUT_RECOVERY:
        return _checkout_recovery_policy(
            recommendation=recommendation,
            context=context,
            config=config,
            failure=failure,
            prob=prob,
            amount=amount,
        )

    # Rule 9 — ESCALATE_TO_HUMAN is honored as human review.
    if action == RecoveryActionType.ESCALATE_TO_HUMAN:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.HUMAN_REVIEW,
            action=None,
            policy_rule=PolicyRule.LOW_CONFIDENCE_ESCALATE,
            reason="Case requires human review.",
            required_safeguards=[],
            thresholds={"escalated": 1.0},
        )

    # Default safety net — unknown action.
    return PolicyDecision(
        approved=False,
        verdict=PolicyVerdict.REJECTED,
        action=None,
        policy_rule=PolicyRule.ACTION_NOT_PERMITTED,
        reason=f"Unhandled action {action.value}.",
        required_safeguards=[],
        thresholds={},
    )


# ---------------------------------------------------------------------------
# Per-action helpers
# ---------------------------------------------------------------------------
def _amount_gate(
    *,
    config: RecoveryConfig,
    amount: int,
    required_safeguards: list[str],
) -> PolicyDecision | None:
    """Apply the maximum-amount safety gate.

    Returns a decision (escalate or reject) when the amount exceeds the
    configured ceiling; otherwise returns ``None`` so the caller can proceed.
    """
    if amount > config.max_payment_amount:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.HUMAN_REVIEW,
            action=None,
            policy_rule=PolicyRule.AMOUNT_ESCALATION,
            reason=(
                f"Amount {amount} paise exceeds the configured max "
                f"{config.max_payment_amount}; escalating to human review."
            ),
            required_safeguards=required_safeguards,
            thresholds={
                "max_payment_amount": float(config.max_payment_amount),
                "amount": float(amount),
            },
        )
    return None


def _retry_policy(
    *,
    recommendation: RecoveryRecommendation,
    context: TransactionContext,
    config: RecoveryConfig,
    failure: str,
    prob: float,
    amount: int,
) -> PolicyDecision:
    required = ["MAX_RETRY_COUNT", "IDEMPOT", "MIN_PROBABILITY"]
    gated = _amount_gate(
        config=config, amount=amount, required_safeguards=required
    )
    if gated is not None:
        return gated

    if (
        failure not in TEMPORARY_FAILURE_REASONS
        or context.previous_retry_count >= config.retry_limit
    ):
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.HUMAN_REVIEW,
            action=None,
            policy_rule=PolicyRule.RETRY_LIMIT_EXCEEDED,
            reason=(
                f"Retry not appropriate for failure_reason='{failure}' "
                f"with previous_retry_count={context.previous_retry_count}."
            ),
            required_safeguards=required,
            thresholds={
                "retry_limit": float(config.retry_limit),
                "previous_retry_count": float(context.previous_retry_count),
            },
        )

    if prob < config.confidence_threshold:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.HUMAN_REVIEW,
            action=None,
            policy_rule=PolicyRule.LOW_CONFIDENCE_ESCALATE,
            reason=(
                f"Recovery probability {prob:.2f} is below threshold "
                f"{config.confidence_threshold:.2f}."
            ),
            required_safeguards=required,
            thresholds={
                "confidence_threshold": config.confidence_threshold,
                "recovery_probability": prob,
            },
        )

    return PolicyDecision(
        approved=True,
        verdict=PolicyVerdict.APPROVED,
        action=RecoveryActionType.RETRY_PAYMENT,
        policy_rule=PolicyRule.HIGH_CONFIDENCE_TEMPORARY_RETRY,
        reason="High-confidence temporary failure with retries remaining.",
        required_safeguards=required,
        thresholds={
            "confidence_threshold": config.confidence_threshold,
            "recovery_probability": prob,
        },
    )


def _alternate_policy(
    *,
    recommendation: RecoveryRecommendation,
    context: TransactionContext,
    config: RecoveryConfig,
    failure: str,
    prob: float,
    amount: int,
) -> PolicyDecision:
    required = ["MIN_PROBABILITY", "IDEMPOT"]
    gated = _amount_gate(
        config=config, amount=amount, required_safeguards=required
    )
    if gated is not None:
        return gated

    if failure not in PERMANENT_FAILURE_REASONS:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.REJECTED,
            action=None,
            policy_rule=PolicyRule.ACTION_NOT_PERMITTED,
            reason=(
                f"SUGGEST_ALTERNATE_PAYMENT_METHOD inappropriate for "
                f"failure_reason='{failure}'."
            ),
            required_safeguards=required,
            thresholds={"failure_reason_match": 0.0},
        )

    if prob < config.confidence_threshold:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.HUMAN_REVIEW,
            action=None,
            policy_rule=PolicyRule.LOW_CONFIDENCE_ESCALATE,
            reason=(
                f"Recovery probability {prob:.2f} below threshold "
                f"{config.confidence_threshold:.2f}; human review."
            ),
            required_safeguards=required,
            thresholds={
                "confidence_threshold": config.confidence_threshold,
                "recovery_probability": prob,
            },
        )

    return PolicyDecision(
        approved=True,
        verdict=PolicyVerdict.APPROVED,
        action=RecoveryActionType.SUGGEST_ALTERNATE_PAYMENT_METHOD,
        policy_rule=PolicyRule.HIGH_CONFIDENCE_PERMANENT_ALTERNATE,
        reason="Permanent decline with sufficient confidence for alternate method.",
        required_safeguards=required,
        thresholds={
            "confidence_threshold": config.confidence_threshold,
            "recovery_probability": prob,
        },
    )


def _payment_link_policy(
    *,
    recommendation: RecoveryRecommendation,
    context: TransactionContext,
    config: RecoveryConfig,
    failure: str,
    prob: float,
    amount: int,
) -> PolicyDecision:
    required = ["MIN_PROBABILITY", "IDEMPOT"]
    gated = _amount_gate(
        config=config, amount=amount, required_safeguards=required
    )
    if gated is not None:
        return gated

    if (
        amount < config.amount_escalation_limit
        or context.previous_retry_count > 0
    ):
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.REJECTED,
            action=None,
            policy_rule=PolicyRule.ACTION_NOT_PERMITTED,
            reason=(
                f"SEND_PAYMENT_LINK requires amount >= {config.amount_escalation_limit} "
                f"and previous_retry_count == 0."
            ),
            required_safeguards=required,
            thresholds={
                "amount_escalation_limit": float(config.amount_escalation_limit),
                "amount": float(amount),
                "previous_retry_count": float(context.previous_retry_count),
            },
        )

    if prob < config.confidence_threshold:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.HUMAN_REVIEW,
            action=None,
            policy_rule=PolicyRule.LOW_CONFIDENCE_ESCALATE,
            reason=(
                f"Recovery probability {prob:.2f} below threshold "
                f"{config.confidence_threshold:.2f}."
            ),
            required_safeguards=required,
            thresholds={
                "confidence_threshold": config.confidence_threshold,
                "recovery_probability": prob,
            },
        )

    return PolicyDecision(
        approved=True,
        verdict=PolicyVerdict.APPROVED,
        action=RecoveryActionType.SEND_PAYMENT_LINK,
        policy_rule=PolicyRule.HIGH_VALUE_PAYMENT_LINK,
        reason="High-value transaction suitable for a payment link.",
        required_safeguards=required,
        thresholds={
            "amount_escalation_limit": float(config.amount_escalation_limit),
            "amount": float(amount),
        },
    )


def _reminder_policy(
    *,
    recommendation: RecoveryRecommendation,
    context: TransactionContext,
    config: RecoveryConfig,
    failure: str,
    prob: float,
    amount: int,
) -> PolicyDecision:
    required = ["MIN_PROBABILITY", "IDEMPOT"]
    gated = _amount_gate(
        config=config, amount=amount, required_safeguards=required
    )
    if gated is not None:
        return gated

    if failure not in CUSTOMER_FAILURE_REASONS:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.REJECTED,
            action=None,
            policy_rule=PolicyRule.ACTION_NOT_PERMITTED,
            reason=(
                f"SEND_REMINDER appropriate only for customer-initiated "
                f"failure_reason='{failure}'."
            ),
            required_safeguards=required,
            thresholds={"failure_reason_match": 0.0},
        )

    if prob < 0.5:
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.HUMAN_REVIEW,
            action=None,
            policy_rule=PolicyRule.LOW_CONFIDENCE_ESCALATE,
            reason=f"Recovery probability {prob:.2f} too low for a reminder.",
            required_safeguards=required,
            thresholds={"min_reminder_probability": 0.5, "recovery_probability": prob},
        )

    return PolicyDecision(
        approved=True,
        verdict=PolicyVerdict.APPROVED,
        action=RecoveryActionType.SEND_REMINDER,
        policy_rule=PolicyRule.CUSTOMER_CANCELLED_REMINDER,
        reason="Customer-initiated event; reminder is appropriate.",
        required_safeguards=required,
        thresholds={"min_reminder_probability": 0.5, "recovery_probability": prob},
    )


def _checkout_recovery_policy(
    *,
    recommendation: RecoveryRecommendation,
    context: TransactionContext,
    config: RecoveryConfig,
    failure: str,
    prob: float,
    amount: int,
) -> PolicyDecision:
    required = ["MIN_PROBABILITY", "IDEMPOT"]
    gated = _amount_gate(
        config=config, amount=amount, required_safeguards=required
    )
    if gated is not None:
        return gated

    if failure != "gateway_degradation":
        return PolicyDecision(
            approved=False,
            verdict=PolicyVerdict.REJECTED,
            action=None,
            policy_rule=PolicyRule.ACTION_NOT_PERMITTED,
            reason="CHECKOUT_RECOVERY requires gateway_degradation root cause.",
            required_safeguards=required,
            thresholds={"failure_reason_match": 0.0},
        )

    return PolicyDecision(
        approved=True,
        verdict=PolicyVerdict.APPROVED,
        action=RecoveryActionType.CHECKOUT_RECOVERY,
        policy_rule=PolicyRule.GATEWAY_DEGRADATION_CHECKOUT_RECOVERY,
        reason="Gateway degradation; alternate checkout path is appropriate.",
        required_safeguards=required,
        thresholds={"recovery_probability": prob},
    )


def summarise_rules() -> Iterable[str]:
    """Human-readable list of policy rules — used by /docs/evaluation.md."""
    return [
        "STOP recommendation → REJECTED / NO_ACTION_NEEDED",
        "Action not in enabled_actions → REJECTED / ACTION_NOT_PERMITTED",
        "RETRY_PAYMENT requires temporary failure + retry<limit + prob>=threshold",
        "SUGGEST_ALTERNATE requires permanent failure + prob>=threshold",
        "SEND_PAYMENT_LINK requires high amount + retry==0 + prob>=threshold",
        "SEND_REMINDER requires customer-initiated failure + prob>=0.5",
        "CHECKOUT_RECOVERY requires gateway_degradation",
        "Amount > max_payment_amount → HUMAN_REVIEW / AMOUNT_ESCALATION",
        "ESCALATE_TO_HUMAN recommendation is honored",
    ]


__all__ = ["evaluate", "summarise_rules", "NON_RETRYABLE_REASONS"]