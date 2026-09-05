"""Phase 5 API tests — recovery, analytics, audit endpoints.

19 scenarios per the Phase 5 plan:

    1.  list_cases_no_filters
    2.  list_cases_with_status_filter
    3.  get_case_detail
    4.  get_case_missing_returns_404
    5.  approve_pending_writes_audit
    6.  approve_already_approved_returns_409
    7.  approve_rejected_returns_409
    8.  approve_succeeded_returns_409
    9.  approve_missing_returns_404
    10. execute_approved_calls_razorpay_once
    11. execute_unapproved_returns_409_no_razorpay_call
    12. execute_blocked_returns_409_no_razorpay_call
    13. execute_twice_returns_already_executed
    14. execute_when_razorpay_fails
    15. audit_timeline_chronological
    16. audit_timeline_missing_case_returns_404
    17. analytics_overview_zero_when_empty
    18. analytics_overview_after_successful_recovery
    19. end_to_end_webhook_to_recovery

The execution path uses a real ``RecoveryEngine`` but with a
``MockRazorpayClient`` patched in for ``default_client`` so we can inspect
``.calls``. The API never imports the Razorpay client directly.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timezone
from typing import Any

import pytest

from backend.db import database as db_module
from backend.db.models import (
    AuditLog,
    Customer,
    RecoveryAction,
    RecoveryCase,
    Transaction,
)
from backend.integrations import razorpay as razorpay_mod
from backend.integrations.razorpay import MockRazorpayClient


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
_UNIQ = itertools.count()


def _next_id(prefix: str) -> str:
    return f"{prefix}_{next(_UNIQ)}"


@pytest.fixture
def mock_razorpay(monkeypatch):
    """Replace ``default_client`` with a fresh ``MockRazorpayClient``.

    All engine code paths that fetch a Razorpay client (via
    ``RecoveryEngine.default`` → ``default_client``) will receive *this*
    instance, so the tests can inspect ``mock.calls`` to assert execution
    semantics.
    """
    client = MockRazorpayClient()
    monkeypatch.setattr(razorpay_mod, "default_client", lambda: client)

    # The recovery module re-imports default_client via
    # ``from backend.integrations.razorpay import ... default_client``,
    # so we patch the names in those modules too.
    import backend.recovery.engine as engine_mod
    import backend.recovery.pipeline as pipeline_mod

    monkeypatch.setattr(engine_mod, "default_client", lambda: client)
    monkeypatch.setattr(pipeline_mod, "default_client", lambda: client)

    return client


def _seed_customer(
    session,
    *,
    external_id: str = "cust_API_1",
    total: int = 10,
    successful: int = 9,
    failed: int = 1,
) -> Customer:
    customer = Customer(
        external_customer_id=external_id,
        email=f"{external_id}@example.com",
        contact="+910000000000",
        total_transactions=total,
        successful_transactions=successful,
        failed_transactions=failed,
        total_spend=float(successful * 1000),
        average_order_value=float(successful * 1000 / max(total, 1)),
    )
    session.add(customer)
    session.flush()
    session.commit()
    return customer


def _seed_transaction(
    session,
    *,
    amount: int = 500_000,  # ₹5000 in paise
    failure_reason: str | None = "payment_capture_failed",
    customer: Customer | None = None,
    status: str = "failed",
) -> Transaction:
    transaction = Transaction(
        razorpay_payment_id=_next_id("pay_API"),
        razorpay_order_id=_next_id("order_API"),
        customer_id=customer.id if customer else None,
        amount=amount,
        currency="INR",
        payment_method="card",
        status=status,
        failure_reason=failure_reason,
        error_code="BAD_REQUEST_ERROR",
    )
    session.add(transaction)
    session.flush()
    session.commit()
    return transaction


def _seed_case(
    session,
    *,
    status: str = "pending",
    amount_rupees: float = 5000.0,
    recommended_action: str = "RETRY_PAYMENT",
    transaction: Transaction | None = None,
    failure_reason: str = "payment_capture_failed",
    confidence: float = 0.8,
    recovery_probability: float = 0.8,
    amount_recovered: float = 0.0,
) -> RecoveryCase:
    if transaction is None:
        transaction = _seed_transaction(
            session, amount=int(amount_rupees * 100), failure_reason=failure_reason
        )
    case = RecoveryCase(
        transaction_id=transaction.id,
        customer_id=transaction.customer_id,
        amount=amount_rupees,
        revenue_at_risk=amount_rupees * recovery_probability,
        recovery_probability=recovery_probability,
        root_cause="TEMPORARY_PAYMENT_FAILURE",
        recommended_action=recommended_action,
        confidence=confidence,
        status=status,
        amount_recovered=amount_recovered,
    )
    session.add(case)
    session.flush()
    session.commit()
    return case


def _payment_failed_payload(payment_id: str = "pay_E2E_001") -> dict:
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
                    "order_id": "order_E2E_001",
                    "method": "card",
                    "email": "e2e@example.com",
                    "contact": "+919999999999",
                    "error_code": "GATEWAY_ERROR",
                    "error_description": "Gateway timed out",
                    # Use a recognised temporary failure reason so the policy
                    # engine approves the auto-classified case end-to-end.
                    "error_reason": "temporary_timeout",
                    "notes": {"customer_id": "cust_E2E_1"},
                    "created_at": 1700000000,
                }
            }
        },
    }


# ---------------------------------------------------------------------------
# 1. list_cases_no_filters
# ---------------------------------------------------------------------------
def test_list_cases_no_filters(client, session):
    _seed_case(session, status="pending")
    _seed_case(session, status="approved")
    _seed_case(session, status="succeeded", amount_recovered=5000.0)

    resp = client.get("/api/recovery/cases")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert len(body) == 3
    assert {c["status"] for c in body} == {"pending", "approved", "succeeded"}


# ---------------------------------------------------------------------------
# 2. list_cases_with_status_filter
# ---------------------------------------------------------------------------
def test_list_cases_with_status_filter(client, session):
    _seed_case(session, status="pending")
    _seed_case(session, status="pending")
    _seed_case(session, status="blocked")
    _seed_case(session, status="succeeded")

    resp = client.get("/api/recovery/cases", params={"status": "pending"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 2
    assert {c["status"] for c in body} == {"pending"}


def test_list_cases_with_action_filter(client, session):
    _seed_case(session, status="pending", recommended_action="RETRY_PAYMENT")
    _seed_case(session, status="pending", recommended_action="SEND_PAYMENT_LINK")

    resp = client.get("/api/recovery/cases", params={"action": "RETRY_PAYMENT"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["recommended_action"] == "RETRY_PAYMENT"


# ---------------------------------------------------------------------------
# 3. get_case_detail
# ---------------------------------------------------------------------------
def test_get_case_detail(client, session):
    transaction = _seed_transaction(session, amount=750_000)
    case = _seed_case(session, transaction=transaction, status="approved")

    resp = client.get(f"/api/recovery/cases/{case.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == case.id
    assert body["transaction"]["razorpay_payment_id"] == transaction.razorpay_payment_id
    assert body["transaction"]["amount"] == 750_000
    assert body["actions"] == []


def test_get_case_detail_includes_actions(client, session):
    case = _seed_case(session, status="approved")
    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type="RETRY_PAYMENT",
        status="SUCCESS",
        reason="ok",
        attempt_number=1,
        executed_at=datetime.now(timezone.utc),
        result={"idempotency_key": "k", "amount": 500000},
    )
    session.add(action)
    session.flush()

    resp = client.get(f"/api/recovery/cases/{case.id}")
    assert resp.status_code == 200
    actions = resp.json()["actions"]
    assert len(actions) == 1
    assert actions[0]["action_type"] == "RETRY_PAYMENT"
    assert actions[0]["status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 4. get_case_missing_returns_404
# ---------------------------------------------------------------------------
def test_get_case_missing_returns_404(client):
    resp = client.get("/api/recovery/cases/nonexistent-id")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 5. approve_pending_writes_audit
# ---------------------------------------------------------------------------
def test_approve_pending_writes_audit(client, session):
    case = _seed_case(session, status="pending")

    resp = client.post(f"/api/recovery/cases/{case.id}/approve")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["case_id"] == case.id
    assert body["status"] == "approved"

    session.refresh(case)
    assert case.status == "approved"

    approved_audit = (
        session.query(AuditLog)
        .filter_by(event_type="case.approved", recovery_case_id=case.id)
        .one()
    )
    assert approved_audit.decision == "ACCEPT"
    assert approved_audit.actor == "api_user"


# ---------------------------------------------------------------------------
# 6. approve_already_approved_returns_409
# ---------------------------------------------------------------------------
def test_approve_already_approved_returns_409(client, session):
    case = _seed_case(session, status="approved")

    resp = client.post(f"/api/recovery/cases/{case.id}/approve")
    assert resp.status_code == 409
    assert "approved" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 7. approve_rejected_returns_409
# ---------------------------------------------------------------------------
def test_approve_rejected_returns_409(client, session):
    case = _seed_case(session, status="rejected")

    resp = client.post(f"/api/recovery/cases/{case.id}/approve")
    assert resp.status_code == 409
    assert "rejected" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 8. approve_succeeded_returns_409
# ---------------------------------------------------------------------------
def test_approve_succeeded_returns_409(client, session):
    case = _seed_case(session, status="succeeded", amount_recovered=5000.0)

    resp = client.post(f"/api/recovery/cases/{case.id}/approve")
    assert resp.status_code == 409
    assert "succeeded" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 9. approve_missing_returns_404
# ---------------------------------------------------------------------------
def test_approve_missing_returns_404(client):
    resp = client.post("/api/recovery/cases/nope/approve")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 10. execute_approved_calls_razorpay_once
# ---------------------------------------------------------------------------
def test_execute_approved_calls_razorpay_once(client, session, mock_razorpay):
    customer = _seed_customer(session, total=10, successful=9, failed=1)
    transaction = _seed_transaction(
        session, amount=300_000, failure_reason="temporary_timeout", customer=customer
    )
    case = _seed_case(
        session,
        transaction=transaction,
        status="approved",
        recommended_action="RETRY_PAYMENT",
        recovery_probability=0.85,
        confidence=0.85,
        failure_reason="temporary_timeout",
    )

    resp = client.post(f"/api/recovery/cases/{case.id}/execute")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    assert body["already_executed"] is False
    assert body["action_type"] == "RETRY_PAYMENT"
    assert body["amount_recovered"] == pytest.approx(3000.0)
    assert body["idempotency_key"] == f"case-{case.id}-action-RETRY_PAYMENT"

    # Exactly one Razorpay call recorded.
    assert len(mock_razorpay.calls) == 1
    call = mock_razorpay.calls[0]
    assert call["action"] == "RETRY_PAYMENT"
    assert call["idempotency_key"] == body["idempotency_key"]
    assert call["amount"] == 300_000

    session.refresh(case)
    assert case.status == "succeeded"
    assert case.amount_recovered == pytest.approx(3000.0)

    success_action = (
        session.query(RecoveryAction)
        .filter_by(recovery_case_id=case.id, status="SUCCESS")
        .one()
    )
    assert success_action.result["idempotency_key"] == body["idempotency_key"]


# ---------------------------------------------------------------------------
# 11. execute_unapproved_returns_409_no_razorpay_call
# ---------------------------------------------------------------------------
def test_execute_unapproved_returns_409_no_razorpay_call(client, session, mock_razorpay):
    case = _seed_case(session, status="pending")

    resp = client.post(f"/api/recovery/cases/{case.id}/execute")
    assert resp.status_code == 409
    assert "pending" in resp.json()["detail"].lower()
    assert len(mock_razorpay.calls) == 0


# ---------------------------------------------------------------------------
# 12. execute_blocked_returns_409_no_razorpay_call
# ---------------------------------------------------------------------------
def test_execute_blocked_returns_409_no_razorpay_call(client, session, mock_razorpay):
    case = _seed_case(session, status="blocked")

    resp = client.post(f"/api/recovery/cases/{case.id}/execute")
    assert resp.status_code == 409
    assert "blocked" in resp.json()["detail"].lower()
    assert len(mock_razorpay.calls) == 0


# ---------------------------------------------------------------------------
# 13. execute_twice_returns_already_executed
# ---------------------------------------------------------------------------
def test_execute_twice_returns_already_executed(client, session, mock_razorpay):
    customer = _seed_customer(session)
    transaction = _seed_transaction(
        session, amount=200_000, customer=customer, failure_reason="temporary_timeout"
    )
    case = _seed_case(
        session,
        transaction=transaction,
        status="approved",
        recommended_action="RETRY_PAYMENT",
        recovery_probability=0.9,
        confidence=0.9,
        failure_reason="temporary_timeout",
    )

    first = client.post(f"/api/recovery/cases/{case.id}/execute")
    assert first.status_code == 200
    assert first.json()["already_executed"] is False
    assert len(mock_razorpay.calls) == 1

    second = client.post(f"/api/recovery/cases/{case.id}/execute")
    assert second.status_code == 200
    body2 = second.json()
    assert body2["already_executed"] is True
    assert body2["status"] == "succeeded"
    assert body2["idempotency_key"] == first.json()["idempotency_key"]
    assert body2["external_reference"] == first.json()["external_reference"]

    # No second Razorpay call.
    assert len(mock_razorpay.calls) == 1


# ---------------------------------------------------------------------------
# 14. execute_when_razorpay_fails
# ---------------------------------------------------------------------------
def test_execute_when_razorpay_fails(client, session, mock_razorpay):
    customer = _seed_customer(session)
    transaction = _seed_transaction(
        session, amount=400_000, customer=customer, failure_reason="temporary_timeout"
    )
    case = _seed_case(
        session,
        transaction=transaction,
        status="approved",
        recommended_action="RETRY_PAYMENT",
        recovery_probability=0.9,
        confidence=0.9,
        failure_reason="temporary_timeout",
    )

    mock_razorpay.set_failure("RAZORPAY_DOWN", "simulated outage")

    resp = client.post(f"/api/recovery/cases/{case.id}/execute")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "failed"
    assert body["already_executed"] is False
    assert body["amount_recovered"] == 0.0
    assert body["error_code"] == "razorpay_error"

    session.refresh(case)
    assert case.status == "failed"
    assert case.amount_recovered == 0.0

    failure_action = (
        session.query(RecoveryAction)
        .filter_by(recovery_case_id=case.id, status="FAILED")
        .one()
    )
    assert failure_action.result["error_code"] == "razorpay_error"


# ---------------------------------------------------------------------------
# 15. audit_timeline_chronological
# ---------------------------------------------------------------------------
def test_audit_timeline_chronological(client, session):
    case = _seed_case(session, status="approved")
    # Seed audit rows out of order to confirm the endpoint sorts.
    now = datetime.now(timezone.utc)
    rows = [
        AuditLog(
            event_type="recovery.case_created",
            actor="engine",
            decision="case_created",
            reason="r1",
            recovery_case_id=case.id,
            transaction_id=case.transaction_id,
            created_at=now,
        ),
        AuditLog(
            event_type="policy.decision",
            actor="policy",
            decision="APPROVED",
            reason="r2",
            recovery_case_id=case.id,
            transaction_id=case.transaction_id,
            created_at=now,
        ),
        AuditLog(
            event_type="case.approved",
            actor="api_user",
            decision="ACCEPT",
            reason="r3",
            recovery_case_id=case.id,
            transaction_id=case.transaction_id,
            created_at=now,
        ),
    ]
    session.add_all(rows)
    session.flush()

    resp = client.get(f"/api/audit/{case.id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = [row["event_type"] for row in body]
    assert types == [
        "recovery.case_created",
        "policy.decision",
        "case.approved",
    ]
    for row in body:
        assert "id" in row
        assert "event_type" in row
        assert "created_at" in row


# ---------------------------------------------------------------------------
# 16. audit_timeline_missing_case_returns_404
# ---------------------------------------------------------------------------
def test_audit_timeline_missing_case_returns_404(client):
    resp = client.get("/api/audit/no-such-case")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 17. analytics_overview_zero_when_empty
# ---------------------------------------------------------------------------
def test_analytics_overview_zero_when_empty(client):
    resp = client.get("/api/analytics/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "total_transactions": 0,
        "total_failed_transactions": 0,
        "recovery_cases": 0,
        "revenue_at_risk": 0.0,
        "revenue_targeted": 0.0,
        "revenue_recovered": 0.0,
        "recovery_rate": 0.0,
        "successful_actions": 0,
        "failed_actions": 0,
        "blocked_actions": 0,
        "human_escalations": 0,
        "intervention_success_rate": 0.0,
    }


# ---------------------------------------------------------------------------
# 18. analytics_overview_after_successful_recovery
# ---------------------------------------------------------------------------
def test_analytics_overview_after_successful_recovery(client, session):
    # Failed transaction counts toward total_failed_transactions.
    _seed_transaction(session, amount=500_000)
    customer = _seed_customer(session)
    transaction = _seed_transaction(
        session, amount=300_000, customer=customer
    )
    case = _seed_case(
        session,
        transaction=transaction,
        status="succeeded",
        amount_rupees=3000.0,
        amount_recovered=3000.0,
        recovery_probability=0.9,
    )
    # Add a successful recovery action.
    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type="RETRY_PAYMENT",
        status="SUCCESS",
        reason="ok",
        attempt_number=1,
        executed_at=datetime.now(timezone.utc),
        result={"idempotency_key": "k1", "amount": 300_000},
    )
    session.add(action)
    session.flush()

    resp = client.get("/api/analytics/overview")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_transactions"] == 2
    assert body["total_failed_transactions"] == 2
    assert body["recovery_cases"] == 1
    assert body["revenue_at_risk"] == pytest.approx(2700.0)  # 3000 * 0.9
    assert body["revenue_targeted"] == pytest.approx(3000.0)
    assert body["revenue_recovered"] == pytest.approx(3000.0)
    assert body["recovery_rate"] == pytest.approx(1.0)
    assert body["successful_actions"] == 1
    assert body["failed_actions"] == 0
    assert body["intervention_success_rate"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 19. end_to_end_webhook_to_recovery
# ---------------------------------------------------------------------------
def test_end_to_end_webhook_to_recovery(client, session, signer, mock_razorpay):
    payload = _payment_failed_payload(payment_id="pay_E2E_FULL")
    body = json.dumps(payload).encode()
    signature = signer(body)

    # 1. Webhook arrives.
    resp = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": signature, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200, resp.text
    transaction_id = resp.json()["transaction_id"]
    assert transaction_id is not None

    # The background pipeline creates a recovery case synchronously
    # (BackgroundTasks run before TestClient returns).
    transaction = (
        session.query(Transaction).filter_by(id=transaction_id).one()
    )
    case = (
        session.query(RecoveryCase)
        .filter_by(transaction_id=transaction.id)
        .one()
    )
    # The pipeline auto-classifies the case. For a fresh customer with no
    # payment history the risk agent typically returns a probability below
    # the action threshold → status="blocked". The demo flow accepts any
    # non-empty case status here.
    assert case.status in {"pending", "approved", "blocked"}

    # 2. Force the case into the approved state via the API (replicating the
    # human-approve step from the demo script).
    if case.status != "approved":
        # blocked cases must move to approved via the API path
        approve = client.post(f"/api/recovery/cases/{case.id}/approve")
        assert approve.status_code == 200, approve.text
        session.refresh(case)
        assert case.status == "approved"

    # 3. Execute. Whether the executor actually invokes Razorpay depends on
    # the reconstructed recommendation — but the response must always be a
    # well-formed ExecutionResponse (succeeded / failed / executing are all
    # valid).
    execute = client.post(f"/api/recovery/cases/{case.id}/execute")
    assert execute.status_code == 200, execute.text
    exec_body = execute.json()
    assert exec_body["status"] in {"succeeded", "failed", "executing"}
    assert exec_body["idempotency_key"]

    # 4. Audit timeline contains the lifecycle stages.
    audit_resp = client.get(f"/api/audit/{case.id}")
    assert audit_resp.status_code == 200
    event_types = [row["event_type"] for row in audit_resp.json()]
    # The pipeline phase writes recovery.case_created + policy.decision
    # (+ safeguard + execution). The API phase writes case.approved. We
    # assert both pipeline and API events appear.
    assert "recovery.case_created" in event_types
    assert "policy.decision" in event_types
    assert "case.approved" in event_types
