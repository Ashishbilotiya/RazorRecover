// TypeScript counterparts of the backend Pydantic schemas.
//
// The backend is the source of truth. If a field name or type diverges here
// from backend/schemas/*.py, fix it here, never silently accept the wrong type.
//
// Money units (gotcha):
//   - TransactionSummary.amount is in PAISE (integer).
//   - CaseSummary.amount, CaseSummary.revenue_at_risk,
//     CaseSummary.amount_recovered, AnalyticsOverview.revenue_* are in RUPEES.
//   - ExecutionResponse.amount_recovered is in RUPEES (engine divides by 100).
//   - RecoveryActionOut.result.amount (when present) is in PAISE.
//
// Status casing (gotcha):
//   - RecoveryCaseStatus values are LOWERCASE ("pending", "approved", ...).
//   - RecoveryActionType and RootCauseCategory values are UPPERCASE.
//   - RecoveryActionOut.status values are UPPERCASE ("SUCCESS"/"FAILED"/"SKIPPED").
//   - ExecutionResponse.status values are LOWERCASE ("executing"/"succeeded"/"failed").
//   - PolicyDecision.verdict is UPPERCASE.

export type RecoveryCaseStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "executing"
  | "succeeded"
  | "failed"
  | "blocked";

export type RecoveryActionType =
  | "RETRY_PAYMENT"
  | "SEND_PAYMENT_LINK"
  | "SEND_REMINDER"
  | "SUGGEST_ALTERNATE_PAYMENT_METHOD"
  | "CHECKOUT_RECOVERY"
  | "ESCALATE_TO_HUMAN"
  | "STOP";

export type RootCauseCategory =
  | "TEMPORARY_PAYMENT_FAILURE"
  | "PERMANENT_PAYMENT_FAILURE"
  | "PAYMENT_METHOD_ISSUE"
  | "CUSTOMER_BEHAVIOR"
  | "GATEWAY_DEGRADATION"
  | "SUBSCRIPTION_FAILURE"
  | "CHECKOUT_ABANDONMENT"
  | "UNKNOWN";

export type PolicyVerdict = "APPROVED" | "REJECTED" | "HUMAN_REVIEW";

export type PolicyRule =
  | "HIGH_CONFIDENCE_TEMPORARY_RETRY"
  | "HIGH_CONFIDENCE_PERMANENT_ALTERNATE"
  | "HIGH_VALUE_PAYMENT_LINK"
  | "CUSTOMER_CANCELLED_REMINDER"
  | "GATEWAY_DEGRADATION_CHECKOUT_RECOVERY"
  | "LOW_CONFIDENCE_ESCALATE"
  | "NO_ACTION_NEEDED"
  | "ACTION_NOT_PERMITTED"
  | "RETRY_LIMIT_EXCEEDED"
  | "AMOUNT_ESCALATION"
  | "PAYMENT_ALREADY_SUCCEEDED";

export type ExecutionStatus = "SUCCESS" | "FAILED" | "SKIPPED";

export type ExecutionResponseStatus =
  | "executing"
  | "succeeded"
  | "failed";

export type AgentSource = "ml" | "llm" | "fallback";

export interface AnalyticsOverview {
  total_transactions: number;
  total_failed_transactions: number;
  recovery_cases: number;
  revenue_at_risk: number; // rupees
  revenue_targeted: number; // rupees
  revenue_recovered: number; // rupees
  recovery_rate: number; // 0..1
  successful_actions: number;
  failed_actions: number;
  blocked_actions: number;
  human_escalations: number;
  intervention_success_rate: number; // 0..1
}

export interface CaseSummary {
  id: string;
  transaction_id: string | null;
  customer_id: string | null;
  amount: number; // rupees
  revenue_at_risk: number; // rupees
  recovery_probability: number; // 0..1
  root_cause: string | null;
  recommended_action: string | null; // RecoveryActionType value (UPPERCASE)
  confidence: number; // 0..1
  status: RecoveryCaseStatus;
  amount_recovered: number; // rupees
  created_at: string; // ISO datetime
  updated_at: string; // ISO datetime
}

export interface TransactionSummary {
  id: string;
  razorpay_payment_id: string;
  razorpay_order_id: string | null;
  customer_id: string | null;
  amount: number; // paise
  currency: string;
  payment_method: string | null;
  status: string;
  failure_reason: string | null;
  error_code: string | null;
  created_at: string;
}

export interface RecoveryActionOut {
  id: string;
  recovery_case_id: string;
  action_type: string; // RecoveryActionType value
  status: string; // ExecutionStatus value (UPPERCASE)
  reason: string | null;
  attempt_number: number;
  executed_at: string | null;
  result: Record<string, unknown> | null;
}

export interface CaseDetail extends CaseSummary {
  transaction: TransactionSummary | null;
  actions: RecoveryActionOut[];
}

export interface ApprovalResponse {
  case_id: string;
  status: "approved";
  approved_at: string;
  message: string;
}

export interface ExecutionResponse {
  case_id: string;
  status: ExecutionResponseStatus;
  action_type: string | null;
  amount_recovered: number; // rupees
  external_reference: string | null;
  idempotency_key: string;
  already_executed: boolean;
  executed_at: string | null;
  error_code: string | null;
  message: string;
}

export interface AuditEventOut {
  id: string;
  event_type: string;
  actor: string;
  decision: string | null;
  reason: string | null;
  metadata: Record<string, unknown> | null; // wire key
  created_at: string;
}

// Narrowed subset of RecoveryActionType most users will see as buttons.
export const RECOVERABLE_ACTIONS: ReadonlySet<RecoveryActionType> = new Set([
  "RETRY_PAYMENT",
  "SEND_PAYMENT_LINK",
  "SEND_REMINDER",
  "SUGGEST_ALTERNATE_PAYMENT_METHOD",
  "CHECKOUT_RECOVERY",
]);

export const STATUS_LABELS: Record<RecoveryCaseStatus, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  executing: "Executing",
  succeeded: "Succeeded",
  failed: "Failed",
  blocked: "Blocked",
};

export const ACTION_LABELS: Record<RecoveryActionType, string> = {
  RETRY_PAYMENT: "Retry payment",
  SEND_PAYMENT_LINK: "Send payment link",
  SEND_REMINDER: "Send reminder",
  SUGGEST_ALTERNATE_PAYMENT_METHOD: "Suggest alternate method",
  CHECKOUT_RECOVERY: "Checkout recovery",
  ESCALATE_TO_HUMAN: "Escalate to human",
  STOP: "Stop",
};

export const ROOT_CAUSE_LABELS: Record<RootCauseCategory, string> = {
  TEMPORARY_PAYMENT_FAILURE: "Temporary payment failure",
  PERMANENT_PAYMENT_FAILURE: "Permanent payment failure",
  PAYMENT_METHOD_ISSUE: "Payment method issue",
  CUSTOMER_BEHAVIOR: "Customer behavior",
  GATEWAY_DEGRADATION: "Gateway degradation",
  SUBSCRIPTION_FAILURE: "Subscription failure",
  CHECKOUT_ABANDONMENT: "Checkout abandonment",
  UNKNOWN: "Unknown",
};

export const POLICY_RULE_LABELS: Record<PolicyRule, string> = {
  HIGH_CONFIDENCE_TEMPORARY_RETRY: "High confidence temporary retry",
  HIGH_CONFIDENCE_PERMANENT_ALTERNATE: "High confidence permanent alternate",
  HIGH_VALUE_PAYMENT_LINK: "High value payment link",
  CUSTOMER_CANCELLED_REMINDER: "Customer cancelled reminder",
  GATEWAY_DEGRADATION_CHECKOUT_RECOVERY: "Gateway degradation checkout recovery",
  LOW_CONFIDENCE_ESCALATE: "Low confidence escalation",
  NO_ACTION_NEEDED: "No action needed",
  ACTION_NOT_PERMITTED: "Action not permitted",
  RETRY_LIMIT_EXCEEDED: "Retry limit exceeded",
  AMOUNT_ESCALATION: "Amount escalation",
  PAYMENT_ALREADY_SUCCEEDED: "Payment already succeeded",
};
