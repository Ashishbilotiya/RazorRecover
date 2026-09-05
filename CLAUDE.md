# RazorRecover — Master Development Specification

You are the lead software architect and senior full-stack/ML engineer responsible for building **RazorRecover**, an AI-powered Revenue Recovery platform for the **Razorpay Buildathon 2026 — Track 03: AI Revenue Recovery**.

You must follow this document as the **single source of truth** for the project.

---

# 1. PRODUCT VISION

## Product Name

**RazorRecover**

## One-line description

> An AI-powered revenue recovery agent that detects recoverable revenue loss, identifies the root cause, selects a safe recovery strategy, executes the approved action through Razorpay Test Mode, and measures the actual revenue recovered.

## Core problem

Merchants continuously lose potential revenue because of:

* Failed payments
* Temporary payment failures
* Checkout abandonment
* Subscription payment failures
* Payment degradation
* Other recoverable payment issues

Traditional systems primarily report these failures.

RazorRecover must go further:

```text
Revenue Loss Event
       ↓
Detect
       ↓
Estimate Revenue at Risk
       ↓
Understand Root Cause
       ↓
Predict Recoverability
       ↓
Select Recovery Strategy
       ↓
Apply Safety Policies
       ↓
Execute Recovery Action
       ↓
Measure Outcome
       ↓
Record Audit Trail
```

The product must demonstrate **actual measurable recovery**, not merely AI recommendations.

---

# 2. HACKATHON OBJECTIVE

The primary objective is to demonstrate:

> **Given a batch of payment/revenue failure events, RazorRecover can identify recoverable revenue, make an intelligent recovery decision, execute a bounded action, and show how much money was actually recovered.**

The final demo must clearly show:

```text
Revenue at Risk
        ↓
Revenue Targeted
        ↓
Recovery Actions
        ↓
Successful Recoveries
        ↓
₹ Revenue Recovered
        ↓
Recovery Rate
```

The system must also demonstrate:

* Compliant escalation
* Stopping rules
* Idempotency
* Auditability
* Explainable decisions
* Safe execution

---

# 3. IMPORTANT DEVELOPMENT PRINCIPLE

## DO NOT OVER-ENGINEER

This is a hackathon project.

Do not create:

* Microservices unless absolutely necessary
* Kubernetes
* Kafka
* Celery unless genuinely required
* Complex event buses
* Multiple databases
* Excessive abstraction layers
* Dozens of interfaces
* Enterprise IAM systems
* Unnecessary design patterns
* Huge configuration systems

Prefer:

```text
FastAPI
PostgreSQL
SQLAlchemy
scikit-learn
LLM
React
Razorpay Test Mode
```

Use clean modular code without unnecessary complexity.

---

# 4. FINAL TECHNOLOGY STACK

## Backend

* Python 3.11+
* FastAPI
* Pydantic
* SQLAlchemy
* PostgreSQL
* Alembic

## ML

* pandas
* NumPy
* scikit-learn
* joblib

## AI / Agents

Use an LLM through a provider abstraction.

The architecture must allow the LLM provider to be changed without rewriting the agent system.

Do not tightly couple business logic to one LLM provider.

## Frontend

* React
* Vite
* JavaScript or TypeScript
* Tailwind CSS

Prefer TypeScript if it does not significantly slow development.

## Integration

* Razorpay Test Mode APIs
* Razorpay Webhooks

## Testing

* pytest
* FastAPI TestClient

## Deployment

Keep deployment simple and hackathon-friendly.

---

# 5. DIRECTORY STRUCTURE

Use this structure unless there is a strong technical reason to change it.

```text
razorrecover/
│
├── README.md
├── CLAUDE.md
├── .env.example
├── .gitignore
├── docker-compose.yml
├── requirements.txt
│
├── backend/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── webhooks.py
│   │   ├── recovery.py
│   │   ├── transactions.py
│   │   └── analytics.py
│   │
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── risk_agent.py
│   │   ├── root_cause_agent.py
│   │   ├── recovery_agent.py
│   │   └── prompts/
│   │       ├── risk_agent.md
│   │       ├── root_cause_agent.md
│   │       └── recovery_agent.md
│   │
│   ├── recovery/
│   │   ├── engine.py
│   │   ├── policies.py
│   │   ├── executor.py
│   │   └── safeguards.py
│   │
│   ├── ml/
│   │   ├── features.py
│   │   ├── model.py
│   │   ├── inference.py
│   │   └── evaluation.py
│   │
│   ├── integrations/
│   │   └── razorpay.py
│   │
│   ├── db/
│   │   ├── database.py
│   │   ├── models.py
│   │   └── repository.py
│   │
│   ├── schemas/
│   │   ├── transaction.py
│   │   ├── recovery.py
│   │   └── webhook.py
│   │
│   └── audit/
│       └── logger.py
│
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.jsx
│       ├── api.js
│       ├── components/
│       │   ├── Dashboard.jsx
│       │   ├── RecoveryCases.jsx
│       │   ├── TransactionTable.jsx
│       │   ├── RecoveryMetrics.jsx
│       │   └── AuditTimeline.jsx
│       └── pages/
│           └── DashboardPage.jsx
│
├── data/
│   ├── synthetic_transactions.csv
│   └── generate_data.py
│
├── models/
│   └── recovery_model.pkl
│
├── tests/
│   ├── test_webhooks.py
│   ├── test_recovery.py
│   ├── test_policies.py
│   └── test_end_to_end.py
│
├── scripts/
│   ├── seed_data.py
│   └── simulate_failures.py
│
└── docs/
    ├── architecture.md
    ├── demo-flow.md
    └── evaluation.md
```

Do not create additional directories unless they solve a real problem.

---

# 6. CORE ARCHITECTURE

The system must follow this architecture:

```text
                    RAZORPAY
                       │
                APIs + Webhooks
                       │
                       ▼
              ┌─────────────────┐
              │ Event Ingestion │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │   PostgreSQL    │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │ Feature Engine  │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │  ML Risk Model  │
              └────────┬────────┘
                       ↓
              ┌─────────────────┐
              │ Agent Pipeline  │
              └────────┬────────┘
                       ↓
             ┌────────────────────┐
             │ Recovery Strategy  │
             └──────────┬─────────┘
                        ↓
             ┌────────────────────┐
             │ Policy + Safeguard │
             └──────────┬─────────┘
                        ↓
             ┌────────────────────┐
             │ Recovery Executor  │
             └──────────┬─────────┘
                        ↓
                    RAZORPAY
                        ↓
                Recovery Result
                        ↓
             ┌────────────────────┐
             │ Measurement + Audit│
             └────────────────────┘
```

---

# 7. PRIMARY MVP USE CASE

Do not implement every possible revenue-recovery scenario initially.

The first and most important use case is:

# Failed Payment Recovery

Example:

```text
Customer attempts ₹5,000 payment

Payment fails

        ↓

System receives failure event

        ↓

Analyze transaction/customer history

        ↓

Predict recovery probability

        ↓

Estimate revenue at risk

        ↓

Identify root cause

        ↓

Choose recovery strategy

        ↓

Validate strategy against safety policies

        ↓

Execute supported recovery action

        ↓

Observe result

        ↓

Record ₹ recovered
```

Only after this complete flow works should additional scenarios be added.

---

# 8. SECONDARY USE CASES

After the primary MVP works, support:

## Checkout abandonment

Detect:

```text
Customer
→ Product
→ Cart
→ Checkout
→ No successful payment
```

Estimate recoverability and trigger an appropriate recovery workflow.

## Subscription payment failure

Detect failed recurring payments and initiate bounded recovery actions.

## Payment degradation

Detect sudden drops in payment success rate and estimate revenue at risk.

These are secondary.

Never allow secondary features to delay the working primary MVP.

---

# 9. EVENT INGESTION

Create:

```text
POST /api/webhooks/razorpay
```

The endpoint must:

1. Receive Razorpay webhook
2. Verify webhook authenticity/signature
3. Extract event type
4. Check idempotency
5. Store the raw/normalized event
6. Convert relevant events into internal transaction events
7. Trigger the recovery pipeline

Important:

A webhook may arrive more than once.

Therefore:

```text
event_id already processed?
        │
     ┌──┴──┐
    YES    NO
     │      │
   ignore  process
```

Never process the same recovery event twice.

---

# 10. DATABASE

Keep the schema simple.

## Transaction

Fields should include approximately:

```text
id
razorpay_payment_id
razorpay_order_id
customer_id
amount
currency
payment_method
status
failure_reason
created_at
updated_at
```

## Customer

```text
id
external_customer_id
total_transactions
successful_transactions
failed_transactions
total_spend
average_order_value
last_successful_payment
```

## RecoveryCase

```text
id
transaction_id
customer_id
amount
revenue_at_risk
recovery_probability
root_cause
recommended_action
confidence
status
amount_recovered
created_at
updated_at
```

## RecoveryAction

```text
id
recovery_case_id
action_type
status
reason
attempt_number
executed_at
result
```

## WebhookEvent

```text
id
external_event_id
event_type
payload
processed
created_at
```

## AuditLog

```text
id
recovery_case_id
event_type
actor
decision
reason
metadata
timestamp
```

Do not store unnecessary sensitive information.

---

# 11. ML SYSTEM

The ML system should predict:

> **Probability that a failed transaction can be successfully recovered.**

Example:

```text
Transaction amount: ₹5,000
Customer success rate: 92%
Previous successful transactions: 8
Previous failures: 1
Failure reason: timeout
Retry count: 0

Recovery probability = 0.87
```

Then:

```text
Revenue at Risk
=
Transaction Amount × Recovery Probability
```

Example:

```text
₹5,000 × 0.87 = ₹4,350
```

This is an estimate, not guaranteed revenue.

---

# 12. ML FEATURES

Start with useful, explainable features.

Possible features:

```text
amount
payment_method
failure_reason
customer_transaction_count
customer_success_rate
customer_failure_rate
customer_total_spend
average_order_value
previous_retry_count
time_since_last_success
hour_of_day
day_of_week
merchant_success_rate
payment_method_success_rate
recent_failure_rate
```

Do not create meaningless features just to increase complexity.

---

# 13. ML MODEL

Start with a simple baseline.

Preferred order:

```text
Logistic Regression
        ↓
Random Forest
        ↓
Optional XGBoost
```

Use the simplest model that performs well.

The model must be evaluated on a held-out test set.

Track:

```text
Precision
Recall
F1
ROC-AUC
Confusion Matrix
Calibration
```

Also track business metrics:

```text
Revenue targeted
Revenue recovered
Recovery rate
False intervention rate
Successful recovery rate
```

---

# 14. SYNTHETIC DATA

Because we may not have access to a real merchant's historical dataset, generate realistic synthetic data.

Create:

```text
data/generate_data.py
```

Generate enough data for meaningful experiments.

The synthetic data should contain realistic patterns.

Examples:

### Recoverable failure

```text
High customer success rate
+
Temporary timeout
+
Low retry count
=
High recovery probability
```

### Non-recoverable failure

```text
Repeated failures
+
Permanent decline
+
Many previous attempts
=
Low recovery probability
```

### High-value customer

```text
Large transaction
+
Strong payment history
=
Potentially valuable recovery case
```

The generator must create **ground truth** so that model evaluation is possible.

Do not randomly generate labels without a logical relationship to the features.

---

# 15. AGENT ARCHITECTURE

Use three main agents.

```text
                 Orchestrator
                     │
          ┌──────────┼──────────┐
          ↓          ↓          ↓
       Risk       Root Cause   Recovery
       Agent         Agent      Agent
```

---

# 16. RISK AGENT

File:

```text
backend/agents/risk_agent.py
```

Responsibilities:

* Read ML prediction
* Analyze business context
* Determine whether the case is worth recovery
* Produce a structured decision

Output should be structured JSON/Pydantic.

Example:

```json
{
  "is_recoverable": true,
  "recovery_probability": 0.87,
  "revenue_at_risk": 4350,
  "confidence": 0.91
}
```

Do not allow free-form text to control downstream execution.

---

# 17. ROOT CAUSE AGENT

Responsibilities:

Determine why the revenue was lost.

Possible categories:

```text
TEMPORARY_PAYMENT_FAILURE
PERMANENT_PAYMENT_FAILURE
CUSTOMER_BEHAVIOR
PAYMENT_METHOD_ISSUE
GATEWAY_DEGRADATION
SUBSCRIPTION_FAILURE
CHECKOUT_ABANDONMENT
UNKNOWN
```

The agent must use available evidence.

It must not invent transaction facts.

---

# 18. RECOVERY AGENT

Responsibilities:

Select the best recovery strategy.

Possible actions:

```text
RETRY_PAYMENT
SEND_PAYMENT_LINK
SEND_REMINDER
SUGGEST_ALTERNATE_PAYMENT_METHOD
CHECKOUT_RECOVERY
ESCALATE_TO_HUMAN
STOP
```

The agent may recommend an action.

It must **not execute it directly**.

---

# 19. AGENT ORCHESTRATOR

`orchestrator.py` controls:

```text
Input
 ↓
Risk Agent
 ↓
Root Cause Agent
 ↓
Recovery Agent
 ↓
Policy Engine
 ↓
Executor
 ↓
Outcome
```

The orchestrator must handle failures gracefully.

If the LLM fails:

```text
LLM unavailable
      ↓
Fallback deterministic rules
      ↓
Continue safely OR escalate
```

Never fail open.

---

# 20. STRUCTURED AI OUTPUT

All agents must return structured outputs.

Prefer Pydantic models.

Example:

```python
class RecoveryDecision(BaseModel):
    action: RecoveryAction
    confidence: float
    reason: str
    expected_recovery: float
```

Do not parse arbitrary natural-language responses using fragile string matching.

---

# 21. CRITICAL SAFETY ARCHITECTURE

This is one of the most important requirements.

The LLM must NEVER directly call Razorpay financial APIs.

Correct:

```text
LLM
 ↓
Recommendation
 ↓
Policy Engine
 ↓
Safeguards
 ↓
Executor
 ↓
Razorpay
```

Incorrect:

```text
LLM
 ↓
Razorpay API
```

---

# 22. POLICY ENGINE

`backend/recovery/policies.py`

Implement deterministic rules.

Example:

```text
IF payment already succeeded
    → STOP

IF retry_count >= 3
    → STOP

IF confidence < threshold
    → HUMAN_REVIEW

IF amount exceeds configured limit
    → HUMAN_REVIEW

IF action is not allowed
    → REJECT

IF customer is not eligible
    → STOP
```

Policies must never depend on LLM interpretation.

---

# 23. SAFEGUARDS

`backend/recovery/safeguards.py`

Implement:

### Idempotency

Prevent duplicate execution.

### Retry limits

Never retry indefinitely.

### Amount limits

Large-value cases should require human review.

### Stopping rules

Stop when:

* Maximum retries reached
* Payment succeeds
* Recovery probability becomes too low
* Customer is ineligible
* Action becomes unsafe

### Human escalation

Cases outside predefined boundaries must be escalated.

---

# 24. RECOVERY EXECUTOR

`backend/recovery/executor.py`

This is responsible for executing only **approved** actions.

Flow:

```text
Recovery Agent
      ↓
Policy Engine
      ↓
Approved?
  ┌───┴───┐
 YES      NO
  ↓        ↓
Execute   Reject
```

The executor should call `integrations/razorpay.py`.

It must never contain AI reasoning.

---

# 25. RAZORPAY INTEGRATION

All Razorpay-specific logic belongs in:

```text
backend/integrations/razorpay.py
```

Do not scatter Razorpay API calls across agents.

Use environment variables:

```text
RAZORPAY_KEY_ID
RAZORPAY_KEY_SECRET
RAZORPAY_WEBHOOK_SECRET
```

Never hard-code secrets.

Use **Razorpay Test Mode** during development and demonstration.

Never use real money.

---

# 26. WEBHOOK SECURITY

Webhook signatures must be validated before accepting an event.

Invalid webhook:

```text
→ reject
→ log security event
→ do not trigger recovery
```

Valid webhook:

```text
→ normalize
→ store
→ process
```

---

# 27. AUDIT TRAIL

Every important decision must produce an audit event.

Example:

```text
CASE #1842

10:31:02
Payment failed

10:31:03
Revenue risk detected
₹4,999

10:31:04
Recovery probability
87%

10:31:04
Root cause
Temporary timeout

10:31:05
Recommended action
Retry payment

10:31:05
Policy validation
APPROVED

10:31:06
Recovery action
EXECUTED

10:31:10
Result
SUCCESS

10:31:10
Revenue recovered
₹4,999
```

Store concise decision rationale.

Do not store private chain-of-thought.

---

# 28. FRONTEND

The dashboard is extremely important for the hackathon.

The judge should understand the product within 30 seconds.

Main dashboard:

```text
┌───────────────────────────────────────────────┐
│              RAZORRECOVER                    │
│         AI Revenue Recovery                  │
├───────────────────────────────────────────────┤
│                                               │
│ Revenue at Risk       ₹12.4L                  │
│ Revenue Targeted       ₹8.2L                 │
│ Revenue Recovered     ₹3.7L                  │
│ Recovery Rate          45.1%                 │
│                                               │
├───────────────────────────────────────────────┤
│ Active Recovery Cases                         │
├───────────────────────────────────────────────┤
│ Payment ID │ Amount │ Risk │ Action │ Status │
│ ...                                          │
└───────────────────────────────────────────────┘
```

---

# 29. RECOVERY CASE VIEW

When a judge clicks a case, show:

```text
Transaction
₹4,999

Failure
Payment timeout

Recovery probability
87%

Revenue at risk
₹4,349

Root cause
Temporary gateway timeout

AI recommendation
Retry payment

Policy
APPROVED

Action
EXECUTED

Result
SUCCESS

Revenue recovered
₹4,999
```

Also show the audit timeline.

---

# 30. ANALYTICS

Display:

```text
Total transactions
Failed transactions
Revenue at risk
Revenue targeted
Revenue recovered
Recovery rate
Successful recovery actions
Failed recovery actions
Human escalations
Stopped actions
```

Charts should be simple and useful.

Do not build decorative charts that don't communicate business value.

---

# 31. BUSINESS METRICS

These metrics are more important than generic AI metrics.

Calculate:

## Revenue at Risk

```text
sum(amount × recovery_probability)
```

## Revenue Targeted

```text
sum(amount of cases selected for intervention)
```

## Revenue Recovered

```text
sum(amount from successful recovery actions)
```

## Recovery Rate

```text
revenue_recovered / revenue_targeted
```

## Intervention Success Rate

```text
successful_actions / total_actions
```

## False Intervention Rate

Measure cases where the system intervened but recovery was unlikely or inappropriate.

---

# 32. EVALUATION

Create:

```text
docs/evaluation.md
```

Document:

### ML performance

```text
Precision
Recall
F1
ROC-AUC
Calibration
```

### Business performance

```text
Revenue at Risk
Revenue Targeted
Revenue Recovered
Recovery Rate
Successful Actions
False Interventions
```

The model must use a proper train/test split.

Never report training performance as the final model performance.

---

# 33. DEMO MODE

Create:

```text
scripts/simulate_failures.py
```

This should allow us to demonstrate a controlled scenario.

Example:

```text
Normal payment success rate
96%

Inject payment degradation

        ↓

Success rate
74%

        ↓

Revenue at risk
₹4,80,000

        ↓

AI identifies recoverable cases

        ↓

Recovery actions

        ↓

₹1,75,000 recovered
```

The demo should be deterministic enough to reproduce reliably.

---

# 34. DEMO STORY

The final presentation should follow this narrative:

```text
1. Merchant has revenue leakage.

2. RazorRecover continuously receives payment events.

3. A payment fails.

4. System detects revenue risk.

5. ML predicts recoverability.

6. AI determines root cause.

7. AI chooses recovery strategy.

8. Policy engine validates the action.

9. Razorpay Test Mode executes the action.

10. Payment succeeds.

11. Dashboard updates.

12. ₹ recovered is shown.

13. Audit trail explains every step.
```

The key sentence during the demo should be:

> **"We don't just tell the merchant that revenue was lost. We identify recoverable revenue, safely act on it, and prove how much money we recovered."**

---

# 35. DEVELOPMENT PHASES

Claude must implement the system incrementally.

## PHASE 0 — Project Setup

Create:

```text
backend
frontend
data
models
tests
scripts
docs
```

Set up:

* FastAPI
* React
* PostgreSQL
* environment configuration
* basic health endpoint

Do not implement agents yet.

---

## PHASE 1 — Database + Webhooks

Implement:

```text
PostgreSQL
SQLAlchemy
Webhook endpoint
Webhook verification
Idempotency
Transaction storage
Audit event
```

Acceptance criterion:

```text
Razorpay webhook
      ↓
FastAPI
      ↓
Database
      ↓
Audit log
```

must work.

---

## PHASE 2 — Synthetic Dataset + ML

Implement:

```text
generate_data.py
features.py
model.py
inference.py
evaluation.py
```

Train the recovery model.

Save:

```text
models/recovery_model.pkl
```

Acceptance criterion:

Model produces:

```text
recovery_probability
```

for a transaction.

---

## PHASE 3 — Agent Pipeline

Implement:

```text
risk_agent.py
root_cause_agent.py
recovery_agent.py
orchestrator.py
```

All outputs must be structured.

Acceptance criterion:

```text
Transaction
 ↓
Risk
 ↓
Root cause
 ↓
Recovery recommendation
```

works without executing any financial action.

---

## PHASE 4 — Policy + Recovery

Implement:

```text
policies.py
safeguards.py
executor.py
```

Acceptance criterion:

```text
AI recommendation
 ↓
Policy
 ↓
Safeguard
 ↓
Executor
```

works correctly.

Unsafe recommendations must be blocked.

---

## PHASE 5 — Razorpay Test Mode

Connect approved actions to Razorpay Test Mode.

Acceptance criterion:

A complete test recovery can be demonstrated safely.

---

## PHASE 6 — Dashboard

Implement:

```text
Dashboard
Recovery cases
Metrics
Transaction table
Audit timeline
```

Acceptance criterion:

The dashboard shows the complete recovery lifecycle.

---

## PHASE 7 — Testing

Implement:

```text
Webhook tests
Policy tests
Recovery tests
Agent tests
End-to-end test
```

At minimum test:

* Duplicate webhook
* Invalid webhook
* Successful payment
* Failed payment
* Retry limit
* High-value escalation
* Low-confidence escalation
* Successful recovery
* Failed recovery

---

## PHASE 8 — Demo Preparation

Create:

```text
scripts/simulate_failures.py
docs/demo-flow.md
docs/evaluation.md
```

Prepare a deterministic 5–7 minute demo.

---

# 36. CODING RULES

Follow these rules throughout development.

### Rule 1

Write clean, readable Python.

### Rule 2

Use type hints.

### Rule 3

Use Pydantic schemas for API boundaries.

### Rule 4

Keep business logic outside API route handlers.

### Rule 5

Keep Razorpay integration isolated.

### Rule 6

Keep LLM logic isolated.

### Rule 7

Never allow an LLM to directly execute financial actions.

### Rule 8

Never hard-code secrets.

### Rule 9

Never silently swallow exceptions.

### Rule 10

Log meaningful errors.

### Rule 11

Use deterministic rules for money and safety.

### Rule 12

Prefer simple implementations over unnecessary abstractions.

---

# 37. ERROR HANDLING

The system must fail safely.

If:

```text
Razorpay unavailable
```

then:

```text
Do not retry indefinitely.
Mark action as pending/failed.
Log the error.
```

If:

```text
LLM unavailable
```

then:

```text
Use deterministic fallback where safe.
Otherwise escalate.
```

If:

```text
Database unavailable
```

then:

```text
Do not execute financial actions.
```

Never assume success when the result is unknown.

---

# 38. SECURITY

Never commit:

```text
.env
API keys
API secrets
Webhook secrets
LLM keys
Database passwords
```

Only commit:

```text
.env.example
```

Use environment variables.

Validate external input.

Verify Razorpay webhooks.

Prevent duplicate actions.

Never expose secrets to frontend.

---

# 39. WHAT NOT TO BUILD

Do NOT build these unless explicitly required later:

```text
Kubernetes
Microservices
Kafka
Redis
Celery
Vector database
RAG
LangGraph
Complex authentication
Multi-tenant billing
Production payment processing
Real-money transactions
Complex notification infrastructure
Mobile application
Advanced observability platform
```

The project should remain focused on the hackathon objective.

---

# 40. IMPORTANT AI DESIGN PRINCIPLE

Do not make the project:

```text
LLM chatbot + payment API
```

That is not sufficient.

The AI must participate in an actual decision workflow:

```text
Data
 ↓
Prediction
 ↓
Reasoning
 ↓
Decision
 ↓
Safety validation
 ↓
Action
 ↓
Outcome
```

The LLM should add value where reasoning is useful.

ML should add value where prediction is useful.

Deterministic code should control money and safety.

---

# 41. FALLBACK STRATEGY

The system must remain demonstrable even if the LLM provider fails.

Implement a deterministic fallback:

```text
IF failure_reason == temporary_timeout
AND retry_count < 3
AND recovery_probability >= 0.75
THEN
    recommend RETRY_PAYMENT
```

If no safe fallback exists:

```text
ESCALATE_TO_HUMAN
```

This prevents the demo from depending entirely on external LLM availability.

---

# 42. API ENDPOINTS

Initially implement approximately:

```text
GET  /health

POST /api/webhooks/razorpay

GET  /api/transactions

GET  /api/recovery/cases

GET  /api/recovery/cases/{case_id}

POST /api/recovery/cases/{case_id}/approve

POST /api/recovery/cases/{case_id}/execute

GET  /api/analytics/overview

GET  /api/audit/{case_id}
```

Do not create unnecessary endpoints.

---

# 43. FRONTEND API FLOW

The frontend should never call Razorpay directly.

Correct:

```text
React
 ↓
FastAPI
 ↓
Razorpay
```

Never:

```text
React
 ↓
Razorpay secret API
```

---

# 44. OBSERVABILITY

For the hackathon, simple logging is sufficient.

Log:

```text
request
webhook
agent decision
policy decision
recovery action
Razorpay response
recovery outcome
errors
```

Use structured logs where practical.

---

# 45. DOCUMENTATION

`README.md` must explain:

```text
Problem
Solution
Architecture
Tech stack
Setup
Environment variables
Running locally
Generating demo data
Running tests
Running demo
```

`docs/architecture.md` must explain the architecture.

`docs/evaluation.md` must explain model and business metrics.

`docs/demo-flow.md` must explain exactly how to demonstrate the product.

---

# 46. DEVELOPMENT BEHAVIOR FOR CLAUDE

When working on this project:

### Always

1. Inspect the existing code before modifying it.
2. Follow the architecture in this file.
3. Reuse existing utilities.
4. Keep changes focused.
5. Run relevant tests after modifications.
6. Explain important architectural decisions.
7. Prefer incremental implementation.
8. Keep the project runnable after each phase.

### Never

1. Rewrite the entire project unnecessarily.
2. Create duplicate utilities.
3. Create new directories without justification.
4. Replace working code without reason.
5. Add dependencies unnecessarily.
6. Hard-code credentials.
7. Allow LLMs to bypass safety policies.
8. Claim an action succeeded without verifying the result.

---

# 47. IMPLEMENTATION PRIORITY

When forced to choose between features, prioritize:

```text
1. End-to-end recovery flow
2. Revenue recovered measurement
3. Safety / stopping rules
4. Audit trail
5. Razorpay integration
6. ML evaluation
7. Agent quality
8. Dashboard polish
9. Secondary use cases
10. Extra features
```

A working end-to-end system is more valuable than ten incomplete features.

---

# 48. DEFINITION OF DONE

The MVP is considered complete only when this scenario works:

```text
A failed Razorpay test payment is received
        ↓
Webhook is verified
        ↓
Event is stored
        ↓
Transaction is analyzed
        ↓
ML predicts recovery probability
        ↓
Revenue at risk is calculated
        ↓
Root cause is determined
        ↓
Recovery strategy is selected
        ↓
Policy validates the strategy
        ↓
Safeguards pass
        ↓
Recovery action is executed
        ↓
Razorpay result is received
        ↓
Recovery outcome is stored
        ↓
Revenue recovered is calculated
        ↓
Audit trail is created
        ↓
Dashboard updates
```

If this complete flow works reliably, we have a strong hackathon MVP.

---

# 49. FINAL PRODUCT PRINCIPLE

RazorRecover should answer four questions for every revenue-loss event:

```text
1. HOW MUCH MONEY IS AT RISK?

2. WHY IS IT AT RISK?

3. WHAT SHOULD WE DO?

4. HOW MUCH MONEY DID WE ACTUALLY RECOVER?
```

Everything in the architecture should support these four questions.

---

# 50. FIRST TASK

When starting development, DO NOT immediately implement the entire project.

First:

```text
1. Create the directory structure.
2. Create the FastAPI application.
3. Configure PostgreSQL.
4. Create the initial database models.
5. Implement GET /health.
6. Implement the Razorpay webhook endpoint.
7. Implement webhook verification.
8. Implement webhook idempotency.
9. Store normalized payment events.
10. Create the first audit log.
11. Run tests.
```

After completing this phase, stop and report:

```text
PHASE 1 COMPLETE

Implemented:
- ...
- ...
- ...

Tests:
- ...

Known issues:
- ...

Next phase:
- ...
```

Do not proceed to Phase 2 until Phase 1 is working.

# END OF MASTER SPECIFICATION
