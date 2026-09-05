"""Razorpay webhook ingestion endpoint.

Flow:
    1. Read raw body bytes (signature is computed over the raw body).
    2. Verify HMAC-SHA256 signature against RAZORPAY_WEBHOOK_SECRET.
    3. Parse envelope via Pydantic schema.
    4. Idempotency check via ``WebhookEvent.external_event_id`` UNIQUE index.
    5. Persist WebhookEvent + (optional) Transaction + audit log in one txn.
    6. For ``payment.failed`` events with a normalized ``Transaction``, schedule
       the recovery pipeline as a FastAPI ``BackgroundTasks`` job. The response
       returns immediately; the pipeline runs after, with its own DB session.

See CLAUDE.md sections 9, 26, 27, 41.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
    status,
)
from sqlalchemy.orm import Session

from backend.audit.logger import (
    WEBHOOK_DUPLICATE,
    WEBHOOK_NORMALIZED,
    WEBHOOK_PIPELINE_TRIGGERED,
    WEBHOOK_RECEIVED,
    WEBHOOK_REJECTED,
    WEBHOOK_SIGNATURE_INVALID,
    record as record_audit,
)
from backend.db.database import get_db, get_session_factory, get_settings
from backend.db.models import Customer, Order, Transaction, WebhookEvent
from backend.integrations.razorpay import (
    EVENT_ID_HEADER,
    SIGNATURE_HEADER,
    WebhookSchemaError,
    WebhookSignatureError,
    derive_external_event_id,
    parse_webhook_envelope,
    verify_webhook_signature,
)
from backend.recovery.pipeline import trigger_recovery_for_failed_transaction
from backend.schemas.webhook import (
    RazorpayWebhookEnvelope,
    WebhookResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post(
    "/razorpay",
    response_model=WebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="Receive a Razorpay webhook",
)
async def ingest_razorpay_webhook(
    request: Request,
    background: BackgroundTasks,
    x_razorpay_signature: str | None = Header(default=None, alias=SIGNATURE_HEADER),
    x_razorpay_event_id: str | None = Header(default=None, alias=EVENT_ID_HEADER),
    session: Session = Depends(get_db),
) -> WebhookResponse:
    """Ingest a single Razorpay webhook event.

    Returns ``outcome="duplicate"`` for replays, ``outcome="rejected"`` for
    signature/schema failures (HTTP 401/400 respectively), and ``"accepted"``
    on success. We never raise 500 on duplicate replays — the upstream Razorpay
    retry behavior expects 2xx.
    """
    settings = get_settings()
    # Starlette's ``Request.body`` is async; we cache the bytes via await.
    body = await request.body()

    # ---- 1. Signature verification -----------------------------------------
    try:
        verify_webhook_signature(
            body=body,
            signature=x_razorpay_signature,
            secret=settings.razorpay_webhook_secret,
        )
    except WebhookSignatureError as exc:
        logger.warning("Rejected Razorpay webhook: %s", exc)
        record_audit(
            session,
            event_type=WEBHOOK_SIGNATURE_INVALID,
            actor="razorpay",
            decision="REJECT",
            reason=str(exc),
            metadata={"has_signature": x_razorpay_signature is not None},
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        ) from exc

    # ---- 2. Envelope parsing ------------------------------------------------
    try:
        envelope = parse_webhook_envelope(body)
    except WebhookSchemaError as exc:
        logger.warning("Rejected Razorpay webhook: %s", exc)
        record_audit(
            session,
            event_type=WEBHOOK_REJECTED,
            actor="razorpay",
            decision="REJECT",
            reason="schema_invalid",
            metadata={"error": str(exc)},
        )
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload did not match the expected schema",
        ) from exc

    # ---- 3. Idempotency check ---------------------------------------------
    external_event_id = derive_external_event_id(
        envelope, header_event_id=x_razorpay_event_id
    )
    existing = (
        session.query(WebhookEvent)
        .filter(WebhookEvent.external_event_id == external_event_id)
        .one_or_none()
    )
    if existing is not None:
        record_audit(
            session,
            event_type=WEBHOOK_DUPLICATE,
            actor="system",
            decision="IGNORE",
            reason="duplicate_webhook_event",
            webhook_event_id=existing.id,
            metadata={"event_type": envelope.event, "external_event_id": external_event_id},
        )
        session.commit()
        return WebhookResponse(
            outcome="duplicate",
            external_event_id=external_event_id,
            event_type=envelope.event,
            reason="event already processed",
        )

    # ---- 4. Persist raw event ----------------------------------------------
    record_audit(
        session,
        event_type=WEBHOOK_RECEIVED,
        actor="razorpay",
        decision="ACCEPT",
        reason="signature_verified",
        metadata={
            "event_type": envelope.event,
            "account_id": envelope.account_id,
            "external_event_id": external_event_id,
        },
    )

    raw_payload = _raw_envelope_dict(envelope)
    webhook_event = WebhookEvent(
        external_event_id=external_event_id,
        event_type=envelope.event,
        entity=envelope.payload.payment.entity.entity if envelope.payload.payment else "order",
        account_id=envelope.account_id,
        payload=raw_payload,
        payload_signature=x_razorpay_signature,
        processed=False,
    )
    session.add(webhook_event)
    session.flush()  # populate webhook_event.id

    # ---- 5. Normalize into Transaction -------------------------------------
    transaction = _normalize_to_transaction(session, envelope, raw_payload)
    record_audit(
        session,
        event_type=WEBHOOK_NORMALIZED,
        actor="system",
        decision="ACCEPT",
        reason="event_normalized",
        webhook_event_id=webhook_event.id,
        transaction_id=transaction.id if transaction else None,
        metadata={"event_type": envelope.event},
    )

    # ---- 6. Pipeline trigger ------------------------------------------------
    # For payment.failed events with a normalized Transaction we dispatch the
    # recovery pipeline as a BackgroundTask. The pipeline opens its own
    # session and never propagates errors back into the HTTP response.
    pipeline_dispatched = False
    if (
        envelope.event == "payment.failed"
        and transaction is not None
        and (transaction.status or "").lower() == "failed"
    ):
        background.add_task(
            trigger_recovery_for_failed_transaction,
            session_factory=get_session_factory(),
            transaction_id=transaction.id,
        )
        pipeline_dispatched = True

    record_audit(
        session,
        event_type=WEBHOOK_PIPELINE_TRIGGERED,
        actor="system",
        decision=("DISPATCH" if pipeline_dispatched else "OBSERVE"),
        reason=(
            "recovery_pipeline_scheduled" if pipeline_dispatched
            else "no_pipeline_required_for_event"
        ),
        webhook_event_id=webhook_event.id,
        transaction_id=transaction.id if transaction else None,
        metadata={
            "event_type": envelope.event,
            "pipeline_dispatched": pipeline_dispatched,
        },
    )
    webhook_event.processed = True
    webhook_event.processed_at = datetime.now(timezone.utc)

    session.commit()

    return WebhookResponse(
        outcome="accepted",
        external_event_id=external_event_id,
        event_type=envelope.event,
        transaction_id=transaction.id if transaction else None,
    )


# ---------------------------------------------------------------------------
# Helpers (kept private — internal normalization, not part of the API surface).
# ---------------------------------------------------------------------------
def _raw_envelope_dict(envelope: RazorpayWebhookEnvelope) -> dict:
    """Return the envelope as a plain dict for JSON storage."""
    return envelope.model_dump(mode="json")


def _normalize_to_transaction(
    session: Session,
    envelope: RazorpayWebhookEnvelope,
    raw_payload: dict,
) -> Transaction | None:
    """Convert a parsed webhook into a Transaction row (if it carries one).

    - ``payment.*`` events  → upsert Order + Transaction, touch Customer stats.
    - ``order.paid`` etc.  → upsert Order only.
    - Anything else        → no transaction is created.
    """
    payment_wrapper = envelope.payload.payment
    order_wrapper = envelope.payload.order
    payment = payment_wrapper.entity if payment_wrapper is not None else None
    order = order_wrapper.entity if order_wrapper is not None else None

    if order is not None and payment is None:
        _upsert_order(session, order)
        return None

    if payment is None:
        return None

    customer = _upsert_customer(session, payment)
    _upsert_order(session, None, payment=payment)

    existing = (
        session.query(Transaction)
        .filter(Transaction.razorpay_payment_id == payment.id)
        .one_or_none()
    )

    failure_reason = _failure_reason(payment)

    if existing is None:
        transaction = Transaction(
            razorpay_payment_id=payment.id,
            razorpay_order_id=payment.order_id,
            customer_id=customer.id if customer else None,
            amount=payment.amount,
            currency=payment.currency,
            payment_method=payment.method,
            status=payment.status,
            failure_reason=failure_reason,
            error_code=payment.error_code,
            error_description=payment.error_description,
            raw_payload=raw_payload,
        )
        session.add(transaction)
    else:
        existing.status = payment.status
        existing.payment_method = payment.method or existing.payment_method
        existing.failure_reason = failure_reason or existing.failure_reason
        existing.error_code = payment.error_code or existing.error_code
        existing.error_description = payment.error_description or existing.error_description
        existing.raw_payload = raw_payload
        transaction = existing

    if customer is not None:
        customer.total_transactions += 1
        if payment.status == "captured":
            customer.successful_transactions += 1
            customer.total_spend += payment.amount / 100.0
            customer.last_successful_payment = datetime.now(timezone.utc)
        elif payment.status == "failed":
            customer.failed_transactions += 1
        if customer.total_transactions > 0:
            customer.average_order_value = customer.total_spend / customer.total_transactions

    session.flush()
    return transaction


def _upsert_customer(session: Session, payment) -> Customer | None:
    """Resolve a customer from payment metadata, creating one if needed.

    Razorpay sometimes only sends ``email`` / ``contact``; we use the email as
    the external id when no explicit customer id is supplied.
    """
    external_id: str | None = None
    if payment.notes and payment.notes.get("customer_id"):
        external_id = str(payment.notes["customer_id"])
    elif payment.email:
        external_id = f"email:{payment.email}"
    elif payment.contact:
        external_id = f"contact:{payment.contact}"
    if external_id is None:
        return None

    customer = (
        session.query(Customer)
        .filter(Customer.external_customer_id == external_id)
        .one_or_none()
    )
    if customer is None:
        customer = Customer(
            external_customer_id=external_id,
            email=payment.email,
            contact=payment.contact,
        )
        session.add(customer)
        session.flush()
    else:
        if payment.email and not customer.email:
            customer.email = payment.email
        if payment.contact and not customer.contact:
            customer.contact = payment.contact
    return customer


def _upsert_order(
    session: Session,
    order,
    payment=None,
) -> Order | None:
    """Create or update the Order row that the payment attaches to."""
    if order is not None:
        razorpay_order_id = order.id
        amount = order.amount
        currency = order.currency
        status_value = order.status
    elif payment is not None and payment.order_id:
        razorpay_order_id = payment.order_id
        amount = payment.amount
        currency = payment.currency
        status_value = "created"
    else:
        return None

    existing = (
        session.query(Order)
        .filter(Order.razorpay_order_id == razorpay_order_id)
        .one_or_none()
    )
    if existing is None:
        existing = Order(
            razorpay_order_id=razorpay_order_id,
            amount=amount,
            currency=currency,
            status=status_value,
        )
        session.add(existing)
        session.flush()
    elif order is not None:
        existing.amount = amount
        existing.currency = currency
        existing.status = status_value
    return existing


def _failure_reason(payment) -> str | None:
    """Return a single canonical failure reason for failed payments.

    The Phase 5 pipeline + policy engine classify failures by membership in
    sets like ``TEMPORARY_FAILURE_REASONS`` / ``PERMANENT_FAILURE_REASONS``,
    so we must surface the Razorpay ``error_reason`` verbatim. The composite
    ``"reason | description | code"`` form previously used here broke
    classification because substring matching was not implemented in the
    agent. We still keep ``error_code`` + ``error_description`` as separate
    columns on the ``Transaction`` row for diagnostic visibility.
    """
    if payment.status != "failed":
        return None
    if payment.error_reason:
        return payment.error_reason
    if payment.error_code:
        return payment.error_code
    return "payment_failed"


__all__ = ["router"]
