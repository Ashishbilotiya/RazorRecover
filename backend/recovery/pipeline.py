
from __future__ import annotations

import logging
from typing import Callable

from backend.agents.orchestrator import run_pipeline_safely
from backend.audit import logger as audit
from backend.db.database import get_session_factory
from backend.db.models import Customer, Transaction
from backend.db.repository import CaseLookup
from backend.integrations.razorpay import RazorpayClient, default_client
from backend.recovery.engine import (
    RecoveryEngine,
    _build_context_from_transaction,
)
from backend.recovery.policies import evaluate as evaluate_policy
from backend.recovery.safeguards import (
    check as check_safeguards,
    make_context_provider,
)
from backend.recovery.config import load_config

logger = logging.getLogger(__name__)


def trigger_recovery_for_failed_transaction(
    *,
    session_factory: Callable | None = None,
    transaction_id: str,
    razorpay_client: RazorpayClient | None = None,
) -> None:
    """Run the Phase 4 recovery pipeline for one failed transaction.

    Always runs in its own session. Any exception is caught, logged, and
    audited — it never propagates back into the HTTP request that scheduled
    this job (which has already returned its 200 to Razorpay).
    """
    factory = session_factory or get_session_factory()
    client = razorpay_client or default_client()
    try:
        session = factory()
        try:
            transaction = session.get(Transaction, transaction_id)
            if transaction is None:
                logger.warning(
                    "Pipeline skipped: transaction %s no longer exists",
                    transaction_id,
                )
                return
            if (transaction.status or "").lower() != "failed":
                # Already captured/canceled/etc. — nothing to recover.
                logger.info(
                    "Pipeline skipped: transaction %s status=%s",
                    transaction_id,
                    transaction.status,
                )
                return

            customer = (
                session.get(Customer, transaction.customer_id)
                if transaction.customer_id
                else None
            )

            # Idempotent: if we already produced a case for this transaction,
            # do not create a second one. The webhook handler also performs
            # its own check before scheduling us, but the defense-in-depth
            # here protects against retries.
            existing = CaseLookup.get_case_by_transaction(session, transaction.id)
            if existing is not None:
                logger.info(
                    "Pipeline skipped: case already exists for transaction %s",
                    transaction_id,
                )
                return

            engine = RecoveryEngine(
                config=load_config(),
                razorpay_client=client,
                session_factory=factory,
            )
            context = _build_context_from_transaction(transaction, customer)
            engine.process_for_transaction(
                transaction=transaction, customer=customer, context=context
            )
        finally:
            session.close()
    except Exception:  # noqa: BLE001 — must never propagate
        logger.exception(
            "Recovery pipeline failed for transaction=%s", transaction_id
        )
        try:
            audit_session = factory()
            try:
                audit.record(
                    audit_session,
                    event_type=audit.PIPELINE_ERROR,
                    actor="pipeline",
                    decision="ERROR",
                    reason="background_pipeline_crashed",
                    transaction_id=transaction_id,
                    metadata={"transaction_id": transaction_id},
                )
                audit_session.commit()
            finally:
                audit_session.close()
        except Exception:  # noqa: BLE001
            logger.exception("Could not even write the pipeline-error audit row")


__all__ = ["trigger_recovery_for_failed_transaction"]
