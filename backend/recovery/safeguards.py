


from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Iterable

from backend.agents.schemas import (
    RecoveryActionType,
    RecoveryRecommendation,
    RiskAssessment,
    TransactionContext,
)
from backend.recovery.config import RecoveryConfig
from backend.recovery.schemas import (
    PolicyDecision,
    PolicyRule,
    PolicyVerdict,
    SafeguardDecision,
    SafeguardName,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
@dataclass
class SafeguardContext:
    """Inputs that don't fit into the structured schemas.

    Attributes:
        payment_already_succeeded: Razorpay later confirmed a successful payment.
        prior_success_action_count: How many prior SUCCESS rows exist for this case.
        action_already_seen_with_key: True if an action row with this
            ``idempotency_key`` already succeeded (replay protection).
    """

    payment_already_succeeded: bool = False
    prior_success_action_count: int = 0
    action_already_seen_with_key: bool = False


# Type alias for the lookup callback the engine wires up.
ActionLookup = Callable[[str], SafeguardContext]


def make_context_provider(
    payment_already_succeeded: bool = False,
    prior_success_action_count: int = 0,
    *,
    action_already_seen_with_key: bool = False,
) -> ActionLookup:
    """Build a simple lookup function returning a fixed :class:`SafeguardContext`."""

    snapshot = SafeguardContext(
        payment_already_succeeded=payment_already_succeeded,
        prior_success_action_count=prior_success_action_count,
        action_already_seen_with_key=action_already_seen_with_key,
    )

    def _lookup(_idempotency_key: str) -> SafeguardContext:
        return snapshot

    return _lookup


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def check(
    *,
    recommendation: RecoveryRecommendation,
    risk: RiskAssessment,
    context: TransactionContext,
    config: RecoveryConfig,
    policy: PolicyDecision,
    idempotency_key: str,
    lookup: ActionLookup,
    override_human_review: bool = False,
) -> SafeguardDecision:
    """Return a :class:`SafeguardDecision` for an approved or escalated policy.

    Order (short-circuit on first failure):

      1. ``ACTION_PERMITTED`` — policy must have approved the action.
      2. ``PAYMENT_ALREADY_SUCCEEDED`` — short-circuit when Razorpay succeeded.
      3. ``TRANSACTION_VALID`` — amount > 0, has razorpay ids where required.
      4. ``MAX_AMOUNT`` — refuse actions over ``config.max_payment_amount``
         that slipped through the policy gate (defense in depth).
      5. ``MAX_RETRY_COUNT`` — refuse when ``previous_retry_count >= config.retry_limit``.
      6. ``MIN_PROBABILITY`` — refuse when probability < ``config.confidence_threshold``.
      7. ``IDEMPOTENCY`` — refuse when the same key already produced a success.
    """
    required = set(_required_safeguards(policy))

    ctx = lookup(idempotency_key)

    # --- 1. Action permitted?
    if not policy.approved or policy.verdict != PolicyVerdict.APPROVED:
        return _fail(
            SafeguardName.ACTION_PERMITTED,
            "Policy did not approve the action.",
            {"policy_verdict": policy.verdict.value},
            required,
        )

    # --- 2. Payment already succeeded?
    if ctx.payment_already_succeeded:
        return _fail(
            SafeguardName.PAYMENT_ALREADY_SUCCEEDED,
            "Payment already succeeded; no recovery needed.",
            {"payment_succeeded": "1"},
            required,
        )

    # --- 3. Transaction valid?
    validity = _validate_transaction(context, policy)
    if validity is not None:
        name, reason = validity
        return _fail(name, reason, {}, required)

    # --- 4. Max amount?
    if context.amount > config.max_payment_amount:
        return _fail(
            SafeguardName.MAX_AMOUNT,
            f"Amount {context.amount} exceeds max {config.max_payment_amount}.",
            {
                "amount": str(context.amount),
                "max_payment_amount": str(config.max_payment_amount),
            },
            required,
        )

    # --- 5. Retry count?
    if context.previous_retry_count >= config.retry_limit:
        return _fail(
            SafeguardName.MAX_RETRY_COUNT,
            (
                f"previous_retry_count={context.previous_retry_count} "
                f"has reached retry_limit={config.retry_limit}."
            ),
            {
                "previous_retry_count": str(context.previous_retry_count),
                "retry_limit": str(config.retry_limit),
            },
            required,
        )

    # --- 6. Min probability?
    if (
        not override_human_review
        and policy.action is not None
        and risk.recovery_probability < config.confidence_threshold
    ):
        return _fail(
            SafeguardName.MIN_PROBABILITY,
            (
                f"Recovery probability {risk.recovery_probability:.3f} "
                f"is below threshold {config.confidence_threshold:.3f}."
            ),
            {
                "recovery_probability": f"{risk.recovery_probability:.4f}",
                "confidence_threshold": f"{config.confidence_threshold:.4f}",
            },
            required,
        )

    # --- 7. Idempotency?
    if ctx.action_already_seen_with_key:
        return _fail(
            SafeguardName.IDEMPOTENCY,
            "Action with this idempotency_key has already succeeded.",
            {"idempotency_key": idempotency_key},
            required,
        )

    return SafeguardDecision(
        allowed=True,
        failed_safeguard=None,
        reason="All safeguards passed.",
        details={},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fail(
    name: SafeguardName,
    reason: str,
    details: dict[str, str],
    required: set[str],
) -> SafeguardDecision:
    """Helper that records whether the failed safeguard was even required."""
    details = {**details, "expected": "true" if name.value in required else "false"}
    return SafeguardDecision(
        allowed=False,
        failed_safeguard=name,
        reason=reason[:500],
        details=details,
    )


def _validate_transaction(
    context: TransactionContext, policy: PolicyDecision
) -> tuple[SafeguardName, str] | None:
    """Return ``(safeguard, reason)`` if the transaction is invalid."""
    if context.amount <= 0:
        return (
            SafeguardName.TRANSACTION_VALID,
            "Transaction amount is not positive.",
        )
    action = policy.action
    if action in (
        RecoveryActionType.RETRY_PAYMENT,
        RecoveryActionType.SEND_REMINDER,
    ):
        if not context.razorpay_payment_id:
            return (
                SafeguardName.TRANSACTION_VALID,
                f"{action.value} requires razorpay_payment_id.",
            )
    if action in (
        RecoveryActionType.SEND_PAYMENT_LINK,
        RecoveryActionType.CHECKOUT_RECOVERY,
    ):
        if not context.razorpay_order_id:
            return (
                SafeguardName.TRANSACTION_VALID,
                f"{action.value} requires razorpay_order_id.",
            )
    return None


def _required_safeguards(policy: PolicyDecision) -> Iterable[str]:
    return list(policy.required_safeguards)


def required_safeguards_for(rule: PolicyRule) -> list[str]:
    """Static mapping used by tests and the engine."""
    mapping: dict[PolicyRule, list[str]] = {
        PolicyRule.HIGH_CONFIDENCE_TEMPORARY_RETRY: [
            "MAX_RETRY_COUNT",
            "IDEMPOTENCY",
            "MIN_PROBABILITY",
            "TRANSACTION_VALID",
            "ACTION_PERMITTED",
        ],
        PolicyRule.HIGH_CONFIDENCE_PERMANENT_ALTERNATE: [
            "IDEMPOTENCY",
            "MIN_PROBABILITY",
            "TRANSACTION_VALID",
            "ACTION_PERMITTED",
        ],
        PolicyRule.HIGH_VALUE_PAYMENT_LINK: [
            "IDEMPOTENCY",
            "MIN_PROBABILITY",
            "TRANSACTION_VALID",
            "ACTION_PERMITTED",
        ],
        PolicyRule.CUSTOMER_CANCELLED_REMINDER: [
            "IDEMPOTENCY",
            "MIN_PROBABILITY",
            "TRANSACTION_VALID",
            "ACTION_PERMITTED",
        ],
        PolicyRule.GATEWAY_DEGRADATION_CHECKOUT_RECOVERY: [
            "IDEMPOTENCY",
            "MIN_PROBABILITY",
            "TRANSACTION_VALID",
            "ACTION_PERMITTED",
        ],
    }
    return mapping.get(rule, [])


def summarise_safeguards() -> list[str]:
    """Human-readable summary of the safeguard gate."""
    return [
        "ACTION_PERMITTED — policy must have approved the action",
        "PAYMENT_ALREADY_SUCCEEDED — short-circuit if Razorpay succeeded",
        "TRANSACTION_VALID — amount > 0, required Razorpay ids present",
        "MAX_AMOUNT — defense-in-depth on configured ceiling",
        "MAX_RETRY_COUNT — refuse when retries exhausted",
        "MIN_PROBABILITY — refuse when probability below threshold",
        "IDEMPOTENCY — refuse when the same key already succeeded",
    ]


__all__ = [
    "ActionLookup",
    "SafeguardContext",
    "check",
    "make_context_provider",
    "required_safeguards_for",
    "summarise_safeguards",
]
