"""Recovery pipeline: policy engine, safeguards, executor, engine.

See CLAUDE.md sections 21–24. Order of layers:

    Agent Orchestrator → Policy → Safeguards → Executor → Razorpay (Test Mode)
"""

from backend.recovery.config import RecoveryConfig, load_config
from backend.recovery.engine import ProcessResult, RecoveryEngine
from backend.recovery.executor import ExecutorError, execute as execute_action
from backend.recovery.policies import evaluate as evaluate_policy
from backend.recovery.safeguards import (
    ActionLookup,
    SafeguardContext,
    check as check_safeguards,
    make_context_provider,
    required_safeguards_for,
)
from backend.recovery.schemas import (
    ExecutionResult,
    ExecutionStatus,
    PolicyDecision,
    PolicyRule,
    PolicyVerdict,
    RecoveryCaseStatus,
    RecoveryOutcome,
    SafeguardDecision,
    SafeguardName,
)

__all__ = [
    "ActionLookup",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutorError",
    "PolicyDecision",
    "PolicyRule",
    "PolicyVerdict",
    "ProcessResult",
    "RecoveryCaseStatus",
    "RecoveryConfig",
    "RecoveryEngine",
    "RecoveryOutcome",
    "SafeguardContext",
    "SafeguardDecision",
    "SafeguardName",
    "check_safeguards",
    "evaluate_policy",
    "execute_action",
    "load_config",
    "make_context_provider",
    "required_safeguards_for",
]
