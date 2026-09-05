"""Phase 1 webhook tests.

Mandatory scenarios (per CLAUDE.md Phase 1 instructions):
    1. Valid webhook
    2. Invalid webhook signature
    3. Duplicate webhook
    4. Payment failure event
    5. Database persistence
    6. Audit log creation
"""

from __future__ import annotations

import json

from backend.db.models import AuditLog, Customer, Order, Transaction, WebhookEvent


def _payment_failed_payload(payment_id: str = "pay_TEST0001") -> dict:
    return {
        "entity": "event",
        "account_id": "acc_TEST",
        "event": "payment.failed",
        "contains": ["payment"],
        "created_at": 1700000000,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 500000,
                    "currency": "INR",
                    "status": "failed",
                    "order_id": "order_TEST0001",
                    "method": "card",
                    "email": "test@example.com",
                    "contact": "+919999999999",
                    "error_code": "BAD_REQUEST_ERROR",
                    "error_description": "Payment failed",
                    "error_reason": "payment_capture_failed",
                    "notes": {"customer_id": "cust_TEST_1"},
                    "created_at": 1700000000,
                }
            }
        },
    }


def _payment_captured_payload(payment_id: str = "pay_TEST_CAPTURED") -> dict:
    return {
        "entity": "event",
        "account_id": "acc_TEST",
        "event": "payment.captured",
        "contains": ["payment"],
        "created_at": 1700000000,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "entity": "payment",
                    "amount": 499900,
                    "currency": "INR",
                    "status": "captured",
                    "order_id": "order_TEST_CAPTURED",
                    "method": "card",
                    "email": "captured@example.com",
                    "contact": "+919999999998",
                    "notes": {"customer_id": "cust_TEST_2"},
                    "created_at": 1700000000,
                }
            }
        },
    }


# ---------------------------------------------------------------------------
# 1. Valid webhook
# ---------------------------------------------------------------------------
def test_valid_webhook_returns_accepted(client, signer):
    body = json.dumps(_payment_failed_payload()).encode()
    signature = signer(body)

    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["outcome"] == "accepted"
    assert payload["event_type"] == "payment.failed"
    assert payload["external_event_id"] == "payment.failed:pay_TEST0001"
    assert payload["transaction_id"] is not None


# ---------------------------------------------------------------------------
# 2. Invalid signature
# ---------------------------------------------------------------------------
def test_invalid_signature_returns_401(client, session):
    body = json.dumps(_payment_failed_payload()).encode()

    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "deadbeef", "Content-Type": "application/json"},
    )

    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid webhook signature"

    # No transaction / event rows should have been persisted on a rejected call.
    assert session.query(Transaction).count() == 0
    assert session.query(WebhookEvent).count() == 0


def test_missing_signature_returns_401(client):
    body = json.dumps(_payment_failed_payload()).encode()

    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# 3. Duplicate webhook
# ---------------------------------------------------------------------------
def test_duplicate_webhook_returns_duplicate_outcome(client, signer):
    body = json.dumps(_payment_failed_payload()).encode()
    signature = signer(body)

    first = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    assert first.status_code == 200
    assert first.json()["outcome"] == "accepted"

    second = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    assert second.status_code == 200
    assert second.json()["outcome"] == "duplicate"


# ---------------------------------------------------------------------------
# 4. Payment failure event produces a Transaction with failure_reason
# ---------------------------------------------------------------------------
def test_payment_failure_persists_transaction_with_failure_reason(client, session, signer):
    body = json.dumps(_payment_failed_payload(payment_id="pay_FAIL_001")).encode()
    signature = signer(body)

    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text

    tx = session.query(Transaction).filter_by(razorpay_payment_id="pay_FAIL_001").one()
    assert tx.status == "failed"
    assert tx.amount == 500000
    assert tx.failure_reason == "payment_capture_failed"
    assert tx.error_code == "BAD_REQUEST_ERROR"
    assert tx.error_description == "Payment failed"


# ---------------------------------------------------------------------------
# 5. Database persistence (all related tables populated)
# ---------------------------------------------------------------------------
def test_valid_webhook_persists_all_related_tables(client, session, signer):
    body = json.dumps(_payment_failed_payload(payment_id="pay_PERSIST_001")).encode()
    signature = signer(body)

    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text

    # WebhookEvent row
    event = (
        session.query(WebhookEvent)
        .filter_by(external_event_id="payment.failed:pay_PERSIST_001")
        .one()
    )
    assert event.event_type == "payment.failed"
    assert event.processed is True
    assert event.payload_signature == signature

    # Order row
    order = session.query(Order).filter_by(razorpay_order_id="order_TEST0001").one()
    assert order.amount == 500000

    # Customer row + updated stats
    customer = session.query(Customer).filter_by(external_customer_id="cust_TEST_1").one()
    assert customer.email == "test@example.com"
    assert customer.total_transactions == 1
    assert customer.failed_transactions == 1
    assert customer.successful_transactions == 0

    # Transaction row
    tx = session.query(Transaction).filter_by(razorpay_payment_id="pay_PERSIST_001").one()
    assert tx.razorpay_order_id == "order_TEST0001"
    assert tx.customer_id == customer.id


def test_captured_payment_increments_success_stats(client, session, signer):
    body = json.dumps(_payment_captured_payload()).encode()
    signature = signer(body)

    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    customer = session.query(Customer).filter_by(external_customer_id="cust_TEST_2").one()
    assert customer.successful_transactions == 1
    assert customer.failed_transactions == 0
    assert abs(customer.total_spend - 4999.00) < 1e-2
    assert customer.last_successful_payment is not None


# ---------------------------------------------------------------------------
# 6. Audit log creation
# ---------------------------------------------------------------------------
def test_valid_webhook_creates_audit_log(client, session, signer):
    body = json.dumps(_payment_failed_payload(payment_id="pay_AUDIT_001")).encode()
    signature = signer(body)

    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    types = [row.event_type for row in session.query(AuditLog).order_by(AuditLog.created_at)]
    # The webhook stages must appear in order at the head of the audit trail.
    # A `recovery.case_created` row may follow because Phase 5 wires the
    # background pipeline; we don't pin the total length.
    assert types[:3] == [
        "webhook.received",
        "webhook.normalized",
        "webhook.pipeline_triggered",
    ]

    received = session.query(AuditLog).filter_by(event_type="webhook.received").one()
    assert received.decision == "ACCEPT"
    assert received.actor == "razorpay"


def test_invalid_signature_writes_audit_record(client, session):
    body = json.dumps(_payment_failed_payload()).encode()
    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "garbage", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401

    invalid = (
        session.query(AuditLog)
        .filter_by(event_type="webhook.signature_invalid")
        .one()
    )
    assert invalid.decision == "REJECT"
    assert invalid.actor == "razorpay"


def test_duplicate_webhook_audit_record(client, session, signer):
    body = json.dumps(_payment_failed_payload(payment_id="pay_DUP_AUDIT")).encode()
    signature = signer(body)

    client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )

    audit_dup = (
        session.query(AuditLog)
        .filter_by(event_type="webhook.duplicate")
        .one()
    )
    assert audit_dup.decision == "IGNORE"
    assert audit_dup.reason == "duplicate_webhook_event"


# ---------------------------------------------------------------------------
# Bonus: malformed payload
# ---------------------------------------------------------------------------
def test_invalid_payload_returns_400(client, signer):
    body = json.dumps({"not": "a webhook"}).encode()
    signature = signer(body)
    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    assert resp.status_code == 400


def test_health_endpoint(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
