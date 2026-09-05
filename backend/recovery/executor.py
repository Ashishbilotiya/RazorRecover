

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.agents.schemas import RecoveryActionType
from backend.integrations.razorpay import (
    RazorpayClient,
    RazorpayError,
    RazorpayExecutionResult,
)
from backend.recovery.schemas import (
    ExecutionResult,
    ExecutionStatus,
)

logger = logging.getLogger(__name__)


class ExecutorError(Exception):
    """Raised when the executor refuses to call Razorpay."""


def execute(
    *,
    action: RecoveryActionType,
    razorpay_order_id: str | None,
    razorpay_payment_id: str | None,
    amount: int,
    currency: str,
    idempotency_key: str,
    client: RazorpayClient,
    metadata: dict[str, Any] | None = None,
) -> ExecutionResult:
    """Perform one approved recovery action against Razorpay (Test Mode).

    The caller is responsible for verifying that the action was approved by
    the policy engine and passed the safeguards gate. This function performs
    no policy or safeguard reasoning; it simply dispatches to the
    :class:`RazorpayClient` and packages the result.

    On any :class:`RazorpayError` we return ``ExecutionResult(success=False,
    status=FAILED, ...)`` — we never raise out of this function, so the engine
    can persist a deterministic outcome.
    """
    if not idempotency_key:
        raise ExecutorError("idempotency_key is required for every execution")

    if amount <= 0:
        return ExecutionResult(
            success=False,
            status=ExecutionStatus.SKIPPED,
            action=action,
            message="Skipped: amount must be positive.",
            executed_at=_now(),
        )

    try:
        raw: RazorpayExecutionResult = client.execute_action(
            action=action.value,
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            amount=amount,
            currency=currency,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )
    except RazorpayError as exc:
        logger.warning("Razorpay execution failed: %s", exc)
        return ExecutionResult(
            success=False,
            status=ExecutionStatus.FAILED,
            action=action,
            message=str(exc)[:500],
            executed_at=_now(),
            error_code="razorpay_error",
        )

    return ExecutionResult(
        success=raw.success,
        status=ExecutionStatus.SUCCESS if raw.success else ExecutionStatus.FAILED,
        action=action,
        external_reference=raw.external_reference,
        amount=amount,
        message=_message_for(raw),
        executed_at=_now(),
        error_code=raw.error_code,
    )


def _message_for(result: RazorpayExecutionResult) -> str:
    if result.success:
        return f"Razorpay returned external_reference={result.external_reference}"
    return f"Razorpay reported failure ({result.error_code or 'unknown'})"


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["ExecutorError", "execute"]
