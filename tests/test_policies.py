"""Phase 4 tests — Policy engine, safeguards, executor, and engine end-to-end.

Mandatory scenarios from CLAUDE.md Phase 4 / Phase 7 acceptance criteria:

    Policy engine:
      - approve RETRY_PAYMENT for high-confidence temporary failures
      - reject when retry limit exceeded
      - escalate when amount above max_payment_amount
      - escalate when confidence below threshold
      - reject actions not in enabled_actions

    Safeguards:
      - block on idempotency replay
      - block on max-retry-count
      - block on transaction invalid (missing razorpay ids)
      - block on max-amount defense-in-depth
      - block on payment-already-succeeded
      - allow when all pass

    Executor:
      - success on happy path
      - failure when Razorpay raises
      - skip on zero amount

    Engine end-to-end:
      - RETRY_PAYMENT path produces a SUCCESS case with audit chain
      - REJECT path produces a REJECTED case without ever calling Razorpay
      - RazorpayError in execution flow produces a FAILED case (no crash)
"""

from __future__ import annotations

import pytest

from backend.agents.schemas import (
    RecoveryActionType,
    RecoveryRecommendation,
    RiskAssessment,
    RootCauseAssessment,
    RootCauseCategory,
    TransactionContext,
)
from backend.db.models import Customer, Order, Transaction
from backend.integrations.razorpay import MockRazorpayClient
from backend.recovery import (
    RecoveryEngine,
    RecoveryOutcome,
)
from backend.recovery.config import RecoveryConfig
from backend.recovery.executor import execute as execute_action
from backend.recovery.policies import evaluate as evaluate_policy
from backend.recovery.safeguards import (
    SafeguardName,
    check as check_safeguards,
    make_context_provider,
)
from backend.recovery.schemas import (
    ExecutionStatus,
    PolicyRule,
    PolicyVerdict,
    RecoveryCaseStatus,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def default_config() -> RecoveryConfig:
    """Conservative thresholds: deterministic for tests.

    The confidence_threshold is intentionally low (0.5) so unit tests are
    not coupled to the exact ML probability the synthetic model produces.
    Tests that need a higher threshold build their own config.
    """
    return RecoveryConfig(
        retry_limit=3,
        confidence_threshold=0.5,
        amount_escalation_limit=50_000_00,
        max_payment_amount=500_000_00,
        max_retry_attempts_per_case=3,
        enabled_actions=frozenset(
            {
                "RETRY_PAYMENT",
                "SEND_PAYMENT_LINK",
                "SEND_REMINDER",
                "SUGGEST_ALTERNATE_PAYMENT_METHOD",
                "CHECKOUT_RECOVERY",
                "ESCALATE_TO_HUMAN",
                "STOP",
            }
        ),
    )


@pytest.fixture
def context() -> TransactionContext:
    return TransactionContext(
        transaction_id="txn_TEST_1",
        amount=500_000,  # ₹5,000 in paise
        currency="INR",
        payment_method="card",
        failure_reason="temporary_timeout",
        customer_id="cust_TEST_1",
        previous_retry_count=0,
        razorpay_payment_id="pay_TEST_1",
        razorpay_order_id="order_TEST_1",
    )


@pytest.fixture
def risk_assessment(context) -> RiskAssessment:
    return RiskAssessment(
        is_recoverable=True,
        recovery_probability=0.9,
        revenue_at_risk=context.amount * 0.9,
        confidence=0.9,
        reason="High quality customer.",
        source="ml",
    )


@pytest.fixture
def recommendation(context) -> RecoveryRecommendation:
    return RecoveryRecommendation(
        action=RecoveryActionType.RETRY_PAYMENT,
        confidence=0.9,
        reason="High confidence retry.",
        expected_recovery=context.amount * 0.9,
        source="llm",
    )


@pytest.fixture
def root_cause_assessment() -> RootCauseAssessment:
    return RootCauseAssessment(
        root_cause=RootCauseCategory.TEMPORARY_PAYMENT_FAILURE,
        confidence=0.9,
        reason="Temporary gateway blip.",
        source="fallback",
    )


@pytest.fixture
def seeded_transaction(session):
    txn = Transaction(
        id="txn_TEST_1",
        razorpay_payment_id="pay_TEST_1",
        razorpay_order_id="order_TEST_1",
        amount=500_000,
        currency="INR",
        payment_method="card",
        status="failed",
        failure_reason="temporary_timeout",
    )
    order = Order(
        id="order_DB_1",
        razorpay_order_id="order_TEST_1",
        amount=500_000,
        currency="INR",
        status="created",
    )
    customer = Customer(
        id="cust_DB_1",
        external_customer_id="cust_TEST_1",
        total_transactions=10,
        successful_transactions=9,
        failed_transactions=1,
        total_spend=50_000.0,
        average_order_value=5_000.0,
    )
    session.add_all([order, customer, txn])
    session.commit()
    return txn


# ===========================================================================
# POLICY ENGINE TESTS
# ===========================================================================
class TestPolicyEngineRetryPayment:
    def test_high_confidence_temporary_retry_is_approved(
        self, recommendation, risk_assessment, context, default_config
    ):
        decision = evaluate_policy(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
        )
        assert decision.approved is True
        assert decision.verdict == PolicyVerdict.APPROVED
        assert decision.action == RecoveryActionType.RETRY_PAYMENT
        assert decision.policy_rule == PolicyRule.HIGH_CONFIDENCE_TEMPORARY_RETRY
        assert "MAX_RETRY_COUNT" in decision.required_safeguards

    def test_retry_rejected_when_retry_limit_reached(
        self, recommendation, risk_assessment, context, default_config
    ):
        context.previous_retry_count = 3  # equals limit
        decision = evaluate_policy(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
        )
        assert decision.approved is False
        assert decision.verdict == PolicyVerdict.HUMAN_REVIEW
        assert decision.policy_rule == PolicyRule.RETRY_LIMIT_EXCEEDED

    def test_retry_rejected_for_permanent_failure(
        self, recommendation, risk_assessment, context, default_config
    ):
        context.failure_reason = "card_declined"
        decision = evaluate_policy(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
        )
        # Permanent failure shouldn't accept RETRY_PAYMENT
        assert decision.approved is False
        assert decision.policy_rule in (
            PolicyRule.RETRY_LIMIT_EXCEEDED,
            PolicyRule.ACTION_NOT_PERMITTED,
        )

    def test_low_confidence_escalated(
        self, recommendation, risk_assessment, context, default_config
    ):
        risk_assessment.recovery_probability = 0.4
        decision = evaluate_policy(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
        )
        assert decision.approved is False
        assert decision.verdict == PolicyVerdict.HUMAN_REVIEW
        assert decision.policy_rule == PolicyRule.LOW_CONFIDENCE_ESCALATE


class TestPolicyEngineAmountGates:
    def test_amount_above_max_escalates(
        self, recommendation, risk_assessment, context, default_config
    ):
        context.amount = 600_000_00  # 1 crore paise
        decision = evaluate_policy(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
        )
        assert decision.approved is False
        assert decision.verdict == PolicyVerdict.HUMAN_REVIEW
        assert decision.policy_rule == PolicyRule.AMOUNT_ESCALATION


class TestPolicyEngineAllowedActions:
    def test_disabled_action_is_rejected(self, context, default_config):
        cfg = RecoveryConfig(
            retry_limit=default_config.retry_limit,
            confidence_threshold=default_config.confidence_threshold,
            amount_escalation_limit=default_config.amount_escalation_limit,
            max_payment_amount=default_config.max_payment_amount,
            max_retry_attempts_per_case=default_config.max_retry_attempts_per_case,
            enabled_actions=frozenset({"SEND_PAYMENT_LINK"}),
        )
        rec = RecoveryRecommendation(
            action=RecoveryActionType.RETRY_PAYMENT,
            confidence=0.9,
            reason="retry",
            expected_recovery=500_000.0,
        )
        risk = RiskAssessment(
            is_recoverable=True,
            recovery_probability=0.9,
            revenue_at_risk=500_000.0,
            confidence=0.9,
            reason="good",
            source="ml",
        )
        decision = evaluate_policy(
            recommendation=rec, risk=risk, context=context, config=cfg
        )
        assert decision.approved is False
        assert decision.policy_rule == PolicyRule.ACTION_NOT_PERMITTED


class TestPolicyEnginePaymentAlreadySucceeded:
    def test_already_succeeded_rejects(
        self, recommendation, risk_assessment, context, default_config
    ):
        decision = evaluate_policy(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
            payment_already_succeeded=True,
        )
        assert decision.approved is False
        assert decision.policy_rule == PolicyRule.PAYMENT_ALREADY_SUCCEEDED


class TestPolicyEngineStopAndHumanEscalate:
    def test_stop_recommendation_rejected(
        self, risk_assessment, context, default_config
    ):
        rec = RecoveryRecommendation(
            action=RecoveryActionType.STOP,
            confidence=0.0,
            reason="Nothing to recover.",
            expected_recovery=0.0,
        )
        decision = evaluate_policy(
            recommendation=rec,
            risk=risk_assessment,
            context=context,
            config=default_config,
        )
        assert decision.approved is False
        assert decision.policy_rule == PolicyRule.NO_ACTION_NEEDED

    def test_escalate_to_human_honored(
        self, risk_assessment, context, default_config
    ):
        rec = RecoveryRecommendation(
            action=RecoveryActionType.ESCALATE_TO_HUMAN,
            confidence=0.5,
            reason="Need human.",
            expected_recovery=0.0,
        )
        decision = evaluate_policy(
            recommendation=rec,
            risk=risk_assessment,
            context=context,
            config=default_config,
        )
        assert decision.approved is False
        assert decision.verdict == PolicyVerdict.HUMAN_REVIEW


# ===========================================================================
# SAFEGUARDS TESTS
# ===========================================================================
def _approve_policy(recommendation, risk_assessment, context, default_config):
    return evaluate_policy(
        recommendation=recommendation,
        risk=risk_assessment,
        context=context,
        config=default_config,
    )


class TestSafeguardsHappyPath:
    def test_all_safeguards_pass(
        self, recommendation, risk_assessment, context, default_config
    ):
        policy = _approve_policy(
            recommendation, risk_assessment, context, default_config
        )
        provider = make_context_provider(
            payment_already_succeeded=False,
            prior_success_action_count=0,
        )
        decision = check_safeguards(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
            policy=policy,
            idempotency_key="key1",
            lookup=provider,
        )
        assert decision.allowed is True
        assert decision.failed_safeguard is None


class TestSafeguardsBlocks:
    def test_action_permitted_block_when_policy_not_approved(
        self, context, default_config
    ):
        rec = RecoveryRecommendation(
            action=RecoveryActionType.RETRY_PAYMENT,
            confidence=0.0,
            reason="bad",
            expected_recovery=0.0,
        )
        risk = RiskAssessment(
            is_recoverable=True,
            recovery_probability=0.0,
            revenue_at_risk=0.0,
            confidence=0.0,
            reason="n/a",
            source="ml",
        )
        policy = evaluate_policy(
            recommendation=rec, risk=risk, context=context, config=default_config
        )
        policy.approved = False
        policy.verdict = PolicyVerdict.REJECTED
        provider = make_context_provider(False, 0)
        decision = check_safeguards(
            recommendation=rec,
            risk=risk,
            context=context,
            config=default_config,
            policy=policy,
            idempotency_key="k",
            lookup=provider,
        )
        assert decision.allowed is False
        assert decision.failed_safeguard == SafeguardName.ACTION_PERMITTED

    def test_payment_already_succeeded_blocks(
        self, recommendation, risk_assessment, context, default_config
    ):
        policy = _approve_policy(
            recommendation, risk_assessment, context, default_config
        )
        provider = make_context_provider(True, 0)
        decision = check_safeguards(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
            policy=policy,
            idempotency_key="k",
            lookup=provider,
        )
        assert decision.allowed is False
        assert decision.failed_safeguard == SafeguardName.PAYMENT_ALREADY_SUCCEEDED

    def test_max_retry_count_blocks(
        self, recommendation, risk_assessment, context, default_config
    ):
        context.previous_retry_count = 3
        policy = _approve_policy(
            recommendation, risk_assessment, context, default_config
        )
        # Force approval to isolate the safeguard.
        policy.approved = True
        policy.verdict = PolicyVerdict.APPROVED
        provider = make_context_provider(False, 0)
        decision = check_safeguards(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
            policy=policy,
            idempotency_key="k",
            lookup=provider,
        )
        assert decision.allowed is False
        assert decision.failed_safeguard == SafeguardName.MAX_RETRY_COUNT

    def test_max_amount_blocks(
        self, recommendation, risk_assessment, context, default_config
    ):
        # Construct a synthetic approved policy so we isolate the safeguard.
        from backend.recovery.schemas import PolicyDecision

        context.amount = 1_000_000_00  # 10 crore paise — way over default
        policy = PolicyDecision(
            approved=True,
            verdict=PolicyVerdict.APPROVED,
            action=RecoveryActionType.RETRY_PAYMENT,
            policy_rule=PolicyRule.HIGH_CONFIDENCE_TEMPORARY_RETRY,
            reason="synthetic approved",
            required_safeguards=["MAX_AMOUNT"],
            thresholds={},
        )
        provider = make_context_provider(False, 0)
        decision = check_safeguards(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
            policy=policy,
            idempotency_key="k",
            lookup=provider,
        )
        assert decision.allowed is False
        assert decision.failed_safeguard == SafeguardName.MAX_AMOUNT

    def test_idempotency_blocks_replay(
        self, recommendation, risk_assessment, context, default_config
    ):
        policy = _approve_policy(
            recommendation, risk_assessment, context, default_config
        )
        provider = make_context_provider(
            False, 0, action_already_seen_with_key=True
        )
        decision = check_safeguards(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
            policy=policy,
            idempotency_key="dup-key",
            lookup=provider,
        )
        assert decision.allowed is False
        assert decision.failed_safeguard == SafeguardName.IDEMPOTENCY

    def test_min_probability_blocks(
        self, recommendation, risk_assessment, context, default_config
    ):
        from backend.recovery.schemas import PolicyDecision

        risk_assessment.recovery_probability = 0.1
        policy = PolicyDecision(
            approved=True,
            verdict=PolicyVerdict.APPROVED,
            action=RecoveryActionType.RETRY_PAYMENT,
            policy_rule=PolicyRule.HIGH_CONFIDENCE_TEMPORARY_RETRY,
            reason="synthetic approved",
            required_safeguards=["MIN_PROBABILITY"],
            thresholds={},
        )
        provider = make_context_provider(False, 0)
        decision = check_safeguards(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
            policy=policy,
            idempotency_key="k",
            lookup=provider,
        )
        assert decision.allowed is False
        assert decision.failed_safeguard == SafeguardName.MIN_PROBABILITY

    def test_missing_payment_id_blocks(
        self, recommendation, risk_assessment, context, default_config
    ):
        context.razorpay_payment_id = None
        policy = _approve_policy(
            recommendation, risk_assessment, context, default_config
        )
        provider = make_context_provider(False, 0)
        decision = check_safeguards(
            recommendation=recommendation,
            risk=risk_assessment,
            context=context,
            config=default_config,
            policy=policy,
            idempotency_key="k",
            lookup=provider,
        )
        assert decision.allowed is False
        assert decision.failed_safeguard == SafeguardName.TRANSACTION_VALID


# ===========================================================================
# EXECUTOR TESTS
# ===========================================================================
class TestExecutor:
    def test_executor_success(self):
        client = MockRazorpayClient()
        result = execute_action(
            action=RecoveryActionType.RETRY_PAYMENT,
            razorpay_order_id="order_TEST",
            razorpay_payment_id="pay_TEST",
            amount=500_000,
            currency="INR",
            idempotency_key="k1",
            client=client,
        )
        assert result.success is True
        assert result.status == ExecutionStatus.SUCCESS
        assert result.action == RecoveryActionType.RETRY_PAYMENT
        assert client.calls and client.calls[0]["idempotency_key"] == "k1"

    def test_executor_razorpay_error(self):
        client = MockRazorpayClient()
        client.set_failure("server_error", "Razorpay down")
        result = execute_action(
            action=RecoveryActionType.RETRY_PAYMENT,
            razorpay_order_id="order_TEST",
            razorpay_payment_id="pay_TEST",
            amount=500_000,
            currency="INR",
            idempotency_key="k1",
            client=client,
        )
        assert result.success is False
        assert result.status == ExecutionStatus.FAILED
        assert "Razorpay down" in result.message

    def test_executor_skips_zero_amount(self):
        client = MockRazorpayClient()
        result = execute_action(
            action=RecoveryActionType.RETRY_PAYMENT,
            razorpay_order_id="order_TEST",
            razorpay_payment_id="pay_TEST",
            amount=0,
            currency="INR",
            idempotency_key="k1",
            client=client,
        )
        assert result.status == ExecutionStatus.SKIPPED
        assert client.calls == []


# ===========================================================================
# ENGINE END-TO-END TESTS
# ===========================================================================
class TestRecoveryEngineHappyPath:
    def test_retry_payment_executes_against_razorpay_and_succeeds(
        self, session, seeded_transaction, default_config
    ):
        client = MockRazorpayClient()
        engine = RecoveryEngine(
            config=default_config,
            razorpay_client=client,
            session_factory=lambda: session,
        )
        ctx = TransactionContext(
            transaction_id=seeded_transaction.id,
            amount=seeded_transaction.amount,
            currency=seeded_transaction.currency or "INR",
            payment_method="card",
            failure_reason="temporary_timeout",
            customer_id="cust_DB_1",
            previous_retry_count=0,
            razorpay_payment_id="pay_TEST_1",
            razorpay_order_id="order_TEST_1",
            customer_success_rate=0.95,
            customer_failure_rate=0.05,
            merchant_success_rate=0.95,
            payment_method_success_rate=0.95,
        )
        result = engine.process_for_transaction(
            transaction=seeded_transaction, customer=None, context=ctx
        )
        # Outcome shape.
        assert isinstance(result.outcome, RecoveryOutcome)
        assert result.outcome.case_status == RecoveryCaseStatus.SUCCEEDED
        assert result.outcome.execution is not None
        assert result.outcome.execution.success is True
        # Mock client was hit exactly once.
        assert len(client.calls) == 1
        assert client.calls[0]["action"] == "RETRY_PAYMENT"

    def test_policy_rejection_never_calls_razorpay(
        self, session, seeded_transaction, default_config
    ):
        client = MockRazorpayClient()
        engine = RecoveryEngine(
            config=default_config,
            razorpay_client=client,
            session_factory=lambda: session,
        )
        ctx = TransactionContext(
            transaction_id=seeded_transaction.id,
            amount=500,
            currency="INR",
            payment_method="card",
            failure_reason="card_declined",  # permanent
            previous_retry_count=0,
            razorpay_payment_id="pay_TEST_1",
            razorpay_order_id="order_TEST_1",
        )
        result = engine.process_for_transaction(
            transaction=seeded_transaction, customer=None, context=ctx
        )
        # Either blocked (human review) or rejected (action not permitted).
        assert result.outcome.case_status in (
            RecoveryCaseStatus.BLOCKED,
            RecoveryCaseStatus.REJECTED,
        )
        assert client.calls == []

    def test_razorpay_error_yields_failed_outcome_not_crash(
        self, session, seeded_transaction, default_config
    ):
        client = MockRazorpayClient()
        client.set_failure("server_error", "Razorpay unavailable")
        engine = RecoveryEngine(
            config=default_config,
            razorpay_client=client,
            session_factory=lambda: session,
        )
        ctx = TransactionContext(
            transaction_id=seeded_transaction.id,
            amount=seeded_transaction.amount,
            currency="INR",
            payment_method="card",
            failure_reason="temporary_timeout",
            previous_retry_count=0,
            razorpay_payment_id="pay_TEST_1",
            razorpay_order_id="order_TEST_1",
            customer_success_rate=0.95,
        )
        result = engine.process_for_transaction(
            transaction=seeded_transaction, customer=None, context=ctx
        )
        assert result.outcome.execution is not None
        assert result.outcome.execution.success is False
        assert result.outcome.case_status == RecoveryCaseStatus.FAILED

    def test_payment_already_succeeded_blocks(
        self, session, seeded_transaction, default_config
    ):
        seeded_transaction.status = "captured"
        session.commit()
        client = MockRazorpayClient()
        engine = RecoveryEngine(
            config=default_config,
            razorpay_client=client,
            session_factory=lambda: session,
        )
        ctx = TransactionContext(
            transaction_id=seeded_transaction.id,
            amount=seeded_transaction.amount,
            currency="INR",
            payment_method="card",
            failure_reason="temporary_timeout",
            previous_retry_count=0,
            razorpay_payment_id="pay_TEST_1",
            razorpay_order_id="order_TEST_1",
        )
        result = engine.process_for_transaction(
            transaction=seeded_transaction, customer=None, context=ctx
        )
        assert result.outcome.case_status == RecoveryCaseStatus.REJECTED
        assert client.calls == []


class TestRecoveryEngineAuditChain:
    def test_audit_chain_emits_all_required_events(
        self, session, seeded_transaction, default_config
    ):
        from backend.db.models import AuditLog
        from backend.audit import logger as audit_module

        client = MockRazorpayClient()
        engine = RecoveryEngine(
            config=default_config,
            razorpay_client=client,
            session_factory=lambda: session,
        )
        ctx = TransactionContext(
            transaction_id=seeded_transaction.id,
            amount=seeded_transaction.amount,
            currency="INR",
            payment_method="card",
            failure_reason="temporary_timeout",
            previous_retry_count=0,
            razorpay_payment_id="pay_TEST_1",
            razorpay_order_id="order_TEST_1",
            customer_success_rate=0.95,
            customer_failure_rate=0.05,
        )
        engine.process_for_transaction(
            transaction=seeded_transaction, customer=None, context=ctx
        )

        seen_events = {row.event_type for row in session.query(AuditLog).all()}
        for required in (
            audit_module.RECOVERY_CASE_CREATED,
            audit_module.POLICY_DECISION,
            audit_module.SAFEGUARD_DECISION,
            audit_module.EXECUTION_SUCCEEDED,
            audit_module.OUTCOME_RECORDED,
        ):
            assert required in seen_events, f"missing audit event: {required}"
