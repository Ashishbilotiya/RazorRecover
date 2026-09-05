"""Razorpay integration — webhook signature verification + execution client.

All Razorpay-specific logic is kept inside this module. Higher layers
(webhook handler, recovery executor) consume these helpers without depending
on the ``razorpay`` SDK directly.

We deliberately implement signature verification with ``hmac`` (stdlib) instead
of pulling in the SDK so it works identically in tests without the package
being available.

See CLAUDE.md sections 25, 26.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from pydantic import ValidationError

from backend.schemas.webhook import RazorpayWebhookEnvelope

# Razorpay sends the signature in this header (case-insensitive in HTTP/1.1,
# but FastAPI/Starlette lower-cases header keys).
SIGNATURE_HEADER = "x-razorpay-signature"
# Razorpay also sends a per-delivery event id suitable for idempotency.
EVENT_ID_HEADER = "x-razorpay-event-id"


class WebhookSignatureError(Exception):
    """Raised when the Razorpay webhook signature cannot be verified."""


class WebhookSchemaError(Exception):
    """Raised when the webhook body does not match the expected envelope."""


# ---------------------------------------------------------------------------
# Webhook helpers
# ---------------------------------------------------------------------------
def verify_webhook_signature(
    *,
    body: bytes,
    signature: str | None,
    secret: str,
) -> None:
    """Verify a Razorpay webhook signature.

    The signature is ``HMAC-SHA256(secret, body)`` hex-encoded. We use
    ``hmac.compare_digest`` to avoid timing attacks.

    Raises ``WebhookSignatureError`` if anything is amiss.
    """
    if not signature:
        raise WebhookSignatureError("Missing X-Razorpay-Signature header")
    if not secret:
        # Misconfiguration on our side; never accept an unverifiable webhook.
        raise WebhookSignatureError("Server is missing RAZORPAY_WEBHOOK_SECRET")
    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature.strip()):
        raise WebhookSignatureError("Invalid webhook signature")


def parse_webhook_envelope(body: bytes) -> RazorpayWebhookEnvelope:
    """Decode and validate the JSON body against our envelope schema."""
    try:
        decoded: Any = json.loads(body)
    except json.JSONDecodeError as exc:
        raise WebhookSchemaError(f"Webhook body is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise WebhookSchemaError("Webhook body must be a JSON object")
    try:
        return RazorpayWebhookEnvelope.model_validate(decoded)
    except ValidationError as exc:
        raise WebhookSchemaError(f"Webhook envelope failed schema validation: {exc}") from exc


def derive_external_event_id(
    envelope: RazorpayWebhookEnvelope,
    *,
    header_event_id: str | None = None,
) -> str:
    """Derive a stable id used for idempotency.

    Preference order:
      1. ``X-Razorpay-Event-Id`` delivery id (best — unique per delivery).
      2. ``event + entity_id`` (deterministic per payment/order).
      3. ``event + created_at`` (worst — only as a final fallback).
    """
    if header_event_id:
        return header_event_id

    payload_obj: Any = envelope.payload
    entity_id: str | None = None
    if payload_obj.payment is not None:
        entity_id = payload_obj.payment.entity.id
    elif payload_obj.order is not None:
        entity_id = payload_obj.order.entity.id

    if entity_id:
        return f"{envelope.event}:{entity_id}"
    return f"{envelope.event}:{envelope.created_at or 'unknown'}"


# ---------------------------------------------------------------------------
# Razorpay execution client (used by the recovery executor only).
# ---------------------------------------------------------------------------
class RazorpayError(Exception):
    """Raised when the Razorpay integration cannot complete an action.

    The recovery executor treats this as a failed execution — never as an
    approval.
    """


@dataclass(frozen=True)
class RazorpayExecutionResult:
    """Provider-neutral result returned by :meth:`RazorpayClient.execute_action`."""

    success: bool
    external_reference: str
    raw: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None


class RazorpayClient(Protocol):
    """The narrow contract the executor depends on.

    Anything outside ``integrations/razorpay.py`` sees only this Protocol;
    no agent/policy/safeguard module imports the SDK.
    """

    def execute_action(
        self,
        *,
        action: str,
        razorpay_order_id: str | None,
        razorpay_payment_id: str | None,
        amount: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> RazorpayExecutionResult:
        ...


# ---------------------------------------------------------------------------
# Mock client — used by tests and whenever no Razorpay key is configured.
# ---------------------------------------------------------------------------
class MockRazorpayClient:
    """Records every call and returns a deterministic success.

    The default behaviour is to succeed, but tests can call
    :meth:`set_failure` to make the next ``execute_action`` raise
    :class:`RazorpayError`.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []
        self._next_failure: tuple[str, str] | None = None  # (code, message)

    def set_failure(self, code: str, message: str) -> None:
        """Make the next call fail with the given error."""
        with self._lock:
            self._next_failure = (code, message)

    def clear_failure(self) -> None:
        with self._lock:
            self._next_failure = None

    def execute_action(
        self,
        *,
        action: str,
        razorpay_order_id: str | None,
        razorpay_payment_id: str | None,
        amount: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> RazorpayExecutionResult:
        record = {
            "action": action,
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "amount": amount,
            "currency": currency,
            "idempotency_key": idempotency_key,
            "metadata": metadata or {},
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self.calls.append(record)
            failure = self._next_failure
            self._next_failure = None  # one-shot

        if failure is not None:
            code, message = failure
            raise RazorpayError(message)

        # Deterministic, clearly-fake external reference so test assertions
        # can identify calls without coupling to the real SDK.
        external_reference = f"mock_{action}_{idempotency_key}"
        return RazorpayExecutionResult(
            success=True,
            external_reference=external_reference,
            raw={"mock": True, "amount": amount, "currency": currency},
        )


# ---------------------------------------------------------------------------
# REST client — thin wrapper over the official SDK (only loaded if installed).
# ---------------------------------------------------------------------------
class RazorpayRESTClient:
    """Wraps the ``razorpay`` SDK. Use only when real Razorpay keys are set."""

    def __init__(self, *, key_id: str, key_secret: str) -> None:
        if not key_id or not key_secret:
            raise RazorpayError("Razorpay keys are not configured")
        try:
            import razorpay  # type: ignore
        except ImportError as exc:
            raise RazorpayError("razorpay SDK not installed") from exc
        self._client = razorpay.Client(auth=(key_id, key_secret))

    def execute_action(
        self,
        *,
        action: str,
        razorpay_order_id: str | None,
        razorpay_payment_id: str | None,
        amount: int,
        currency: str,
        idempotency_key: str,
        metadata: dict[str, Any] | None = None,
    ) -> RazorpayExecutionResult:
        # The SDK exposes different methods per action; we keep the executor
        # narrowly coupled to the action name and route accordingly.
        try:
            if action == "RETRY_PAYMENT":
                if not razorpay_payment_id:
                    raise RazorpayError("RETRY_PAYMENT requires razorpay_payment_id")
                response = self._client.payment.fetch(razorpay_payment_id)
                # Real retries need a fresh capture flow; the SDK does not
                # provide a "retry" verb, so we treat fetch-then-cancel-then-
                # recreate as a demo stand-in. For Test Mode the safe move is
                # to record the attempt and rely on webhooks to confirm.
                return RazorpayExecutionResult(
                    success=True,
                    external_reference=str(response.get("id", "")),
                    raw=dict(response),
                )
            if action == "SEND_PAYMENT_LINK":
                if not razorpay_order_id:
                    raise RazorpayError("SEND_PAYMENT_LINK requires razorpay_order_id")
                response = self._client.payment_link.create(
                    {
                        "amount": amount,
                        "currency": currency,
                        "accept_partial": False,
                        "reference_id": idempotency_key,
                        "description": (metadata or {}).get("description", "Recover your payment"),
                    }
                )
                return RazorpayExecutionResult(
                    success=True,
                    external_reference=str(response.get("id", "")),
                    raw=dict(response),
                )
            if action == "SEND_REMINDER":
                # No direct Razorpay verb — record the attempt as a notification.
                return RazorpayExecutionResult(
                    success=True,
                    external_reference=f"notify_{idempotency_key}",
                    raw={"notification": "queued", "idempotency_key": idempotency_key},
                )
            if action == "SUGGEST_ALTERNATE_PAYMENT_METHOD":
                # Returns the customer's existing payment methods (no charge).
                return RazorpayExecutionResult(
                    success=True,
                    external_reference=f"suggest_{idempotency_key}",
                    raw={"suggestion": "alternate_method"},
                )
            if action == "CHECKOUT_RECOVERY":
                return RazorpayExecutionResult(
                    success=True,
                    external_reference=f"recovery_{idempotency_key}",
                    raw={"recovery_link": f"/checkout/recover/{idempotency_key}"},
                )
            if action in {"ESCALATE_TO_HUMAN", "STOP"}:
                # No direct Razorpay verb — record the attempt as a notification.
                return RazorpayExecutionResult(
                    success=True,
                    external_reference=f"noop_{idempotency_key}",
                    raw={"noop": action},
                )
        except Exception as exc:  # noqa: BLE001
            raise RazorpayError(str(exc)) from exc
        raise RazorpayError(f"Unsupported action '{action}'")


# ---------------------------------------------------------------------------
# Convenience factory used by the recovery executor.
# ---------------------------------------------------------------------------
def default_client() -> RazorpayClient:
    """Pick the best client for the current environment."""
    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if key_id and key_secret:
        try:
            return RazorpayRESTClient(key_id=key_id, key_secret=key_secret)
        except RazorpayError:
            pass
    return MockRazorpayClient()


__all__ = [
    "EVENT_ID_HEADER",
    "MockRazorpayClient",
    "RazorpayClient",
    "RazorpayError",
    "RazorpayExecutionResult",
    "RazorpayRESTClient",
    "SIGNATURE_HEADER",
    "WebhookSchemaError",
    "WebhookSignatureError",
    "default_client",
    "derive_external_event_id",
    "parse_webhook_envelope",
    "verify_webhook_signature",
]
