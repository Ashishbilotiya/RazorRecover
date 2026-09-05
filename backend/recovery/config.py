

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryConfig:
    """Knobs the policy engine, safeguards, and executor share."""

    retry_limit: int
    confidence_threshold: float
    amount_escalation_limit: int  # paise
    max_payment_amount: int  # paise — refuse actions above this without escalation
    max_retry_attempts_per_case: int
    enabled_actions: frozenset[str]


def _to_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _to_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_config() -> RecoveryConfig:
    """Build a config snapshot from current environment variables."""
    enabled = frozenset(
        action.strip()
        for action in os.environ.get(
            "RECOVERY_ENABLED_ACTIONS",
            "RETRY_PAYMENT,SEND_PAYMENT_LINK,SEND_REMINDER,"
            "SUGGEST_ALTERNATE_PAYMENT_METHOD,CHECKOUT_RECOVERY,"
            "ESCALATE_TO_HUMAN,STOP",
        ).split(",")
        if action.strip()
    )
    return RecoveryConfig(
        retry_limit=_to_int("RECOVERY_RETRY_LIMIT", 3),
        confidence_threshold=_to_float("RECOVERY_CONFIDENCE_THRESHOLD", 0.75),
        amount_escalation_limit=_to_int("RECOVERY_AMOUNT_ESCALATION_LIMIT", 50_000_00),
        # Conservative ceiling — anything above this needs human approval even
        # if the policy would otherwise approve it. Stored in paise (₹5,00,000).
        max_payment_amount=_to_int("RECOVERY_MAX_PAYMENT_AMOUNT", 500_000_00),
        max_retry_attempts_per_case=_to_int("RECOVERY_MAX_RETRY_ATTEMPTS", 3),
        enabled_actions=enabled,
    )


__all__ = ["RecoveryConfig", "load_config"]
