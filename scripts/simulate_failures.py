"""
Deterministic simulation script for the RazorRecover demo.
This script exercises the end-to-end recovery flow:
Transaction -> Pipeline -> Case -> Approval -> Execution -> Outcome.

It covers four key scenarios:
1. Automatic Success: High recoverability, approved by policy, executes immediately.
2. Manual Approval: Medium recoverability, requires human review -> Approved -> Executed.
3. Blocked: Low recoverability, rejected by policy.
4. Idempotency: Re-executing a previously successful case.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.agents.schemas import TransactionContext
from backend.db.database import get_session_factory
from backend.db.models import Customer, Transaction, RecoveryCase
from backend.db.repository import CaseLookup, CaseWriter
from backend.integrations.razorpay import default_client
from backend.recovery.config import load_config
from backend.recovery.engine import RecoveryEngine, _build_context_from_transaction

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def create_demo_customer(session, email: str, success_rate: float) -> Customer:
    """Create a customer with specific success/failure rates."""
    total = 10
    successes = int(total * success_rate)
    failures = total - successes

    customer = Customer(
        external_customer_id=f"cust_{uuid.uuid4().hex[:8]}",
        email=email,
        total_transactions=total,
        successful_transactions=successes,
        failed_transactions=failures,
        total_spend=successes * 1000.0, # Average ₹1000
        average_order_value=1000.0 if total > 0 else 0.0,
    )
    session.add(customer)
    session.flush()
    return customer

def create_demo_transaction(session, customer: Customer, amount: int, reason: str) -> Transaction:
    """Create a failed transaction."""
    transaction = Transaction(
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
        razorpay_order_id=f"ord_{uuid.uuid4().hex[:12]}",
        customer_id=customer.id,
        amount=amount,
        currency="INR",
        payment_method="card",
        status="failed",
        failure_reason=reason,
    )
    session.add(transaction)
    session.flush()
    return transaction

def run_scenario(
    name: str,
    customer_email: str,
    customer_success_rate: float,
    amount: int,
    failure_reason: str,
    manual_approval: bool = False
):
    logger.info(f"--- Scenario: {name} ---")
    factory = get_session_factory()
    engine = RecoveryEngine.default(session_factory=factory)

    with factory() as session:
        # 1. Setup data
        customer = create_demo_customer(session, customer_email, customer_success_rate)
        transaction = create_demo_transaction(session, customer, amount, failure_reason)
        context = _build_context_from_transaction(transaction, customer)

        logger.info(f"Transaction: ₹{amount/100:.2f} | Reason: {failure_reason} | Cust Success Rate: {customer_success_rate:.2%}")

        # 2. Run the pipeline
        result = engine.process_for_transaction(
            transaction=transaction,
            customer=customer,
            context=context
        )

        # Re-fetch the case using the current session to avoid DetachedInstanceError
        case = session.get(RecoveryCase, result.case.id)
        if case is None:
            logger.error(f"Case {result.case.id} disappeared after processing")
            return

        logger.info(f"Case created: {case.id} | Status: {case.status} | Prob: {case.recovery_probability:.2%}")

        # 3. Handle Manual Approval if required
        if manual_approval and case.status == "blocked":
            logger.info("Simulating Manual Approval: Updating status to 'approved'...")
            CaseWriter.update_case(session, case, status="approved")
            session.commit()

            # Execute the approved case
            exec_result = engine.execute_approved_case(case_id=case.id)
            if hasattr(exec_result, "outcome"):
                outcome = exec_result.outcome
                recovered_amount = 0.0
                if outcome.execution:
                    recovered_amount = outcome.execution.amount / 100.0

                logger.info(f"Execution Outcome: {outcome.case_status.value} | Recovered: ₹{recovered_amount:.2f}")
            else:
                logger.info("Case was already executed.")
        else:
            logger.info(f"Final Case Status: {case.status} | Recovered: ₹{case.amount_recovered:.2f}")

    logger.info("\n")

def test_idempotency(success_case_id: str | None):
    if not success_case_id:
        logger.warning("No success_case_id provided, skipping idempotency test.")
        return

    logger.info(f"--- Scenario: Idempotency ---")
    factory = get_session_factory()
    engine = RecoveryEngine.default(session_factory=factory)

    with factory() as session:
        case = session.get(RecoveryCase, success_case_id)
        if not case:
            logger.error(f"Case {success_case_id} not found.")
            return

        if case.status != "succeeded":
            logger.warning(f"Case {case.id} is not 'succeeded', skipping idempotency test.")
            return

        logger.info(f"Replaying successful case: {case.id}")
        result = engine.execute_approved_case(case_id=case.id)

        from backend.recovery.engine import AlreadyExecuted
        if isinstance(result, AlreadyExecuted):
            logger.info("SUCCESS: Idempotency check passed. Received 'AlreadyExecuted' sentinel.")
        else:
            logger.error("FAILURE: Idempotency check failed. Executor ran again.")

if __name__ == "__main__":
    # Clear previous demo data for a clean run
    factory = get_session_factory()
    with factory() as session:
        from backend.db.models import Transaction, Customer, RecoveryCase, RecoveryAction, Order, WebhookEvent, AuditLog
        session.query(RecoveryAction).delete()
        session.query(RecoveryCase).delete()
        session.query(Transaction).delete()
        session.query(Customer).delete()
        session.query(Order).delete()
        session.query(WebhookEvent).delete()
        session.query(AuditLog).delete()
        session.commit()

    # Track a successful case for idempotency test
    success_id = None

    # Scenario 1: Automatic Success (High recoverability, Temporary Timeout)
    factory = get_session_factory()
    engine = RecoveryEngine.default(session_factory=factory)
    with factory() as session:
        customer = create_demo_customer(session, "success@example.com", 1.0)
        transaction = create_demo_transaction(session, customer, 500000, "temporary_timeout")
        context = _build_context_from_transaction(transaction, customer)
        result = engine.process_for_transaction(transaction=transaction, customer=customer, context=context)
        success_id = result.case.id
        logger.info(f"Automatic Success Case: {success_id} | Status: {result.case.status}")

    # Scenario 2: Manual Approval (Medium recoverability -> Blocked -> Approved -> Success)
    run_scenario(
        "Manual Approval",
        "manual@example.com",
        0.60,
        100000, # ₹1,000
        "payment_method_issue",
        manual_approval=True
    )

    # Scenario 3: Blocked/Rejected (Low recoverability, Permanent Decline)
    run_scenario(
        "Blocked/Rejected",
        "fail@example.com",
        0.10,
        200000, # ₹2,000
        "permanent_decline"
    )

    # Scenario 4: Idempotency
    test_idempotency(success_id)

    logger.info("Simulation complete. Check the Dashboard to verify results.")
