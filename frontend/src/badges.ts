// Single source of truth for status colours, labels, and audit-event friendly
// titles. Keep this file in sync with backend/recovery/schemas.py and
// backend/audit/logger.py.

import type { RecoveryCaseStatus } from "./types";

export interface StatusBadgeMeta {
  label: string;
  // Tailwind classes for the badge background + text + ring.
  classes: string;
  // Dot colour (background colour for a 6px circle).
  dot: string;
}

export const CASE_STATUS_META: Record<RecoveryCaseStatus, StatusBadgeMeta> = {
  pending: {
    label: "Pending",
    classes: "bg-amber-50 text-amber-800 ring-1 ring-inset ring-amber-200",
    dot: "bg-amber-500",
  },
  approved: {
    label: "Approved",
    classes: "bg-blue-50 text-blue-800 ring-1 ring-inset ring-blue-200",
    dot: "bg-blue-500",
  },
  rejected: {
    label: "Rejected",
    classes: "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200",
    dot: "bg-slate-400",
  },
  executing: {
    label: "Executing",
    classes:
      "bg-blue-50 text-blue-800 ring-1 ring-inset ring-blue-200 animate-pulse",
    dot: "bg-blue-500",
  },
  succeeded: {
    label: "Succeeded",
    classes: "bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200",
    dot: "bg-emerald-500",
  },
  failed: {
    label: "Failed",
    classes: "bg-rose-50 text-rose-800 ring-1 ring-inset ring-rose-200",
    dot: "bg-rose-500",
  },
  blocked: {
    label: "Blocked",
    classes: "bg-orange-50 text-orange-800 ring-1 ring-inset ring-orange-200",
    dot: "bg-orange-500",
  },
};

export const ACTION_STATUS_META: Record<string, StatusBadgeMeta> = {
  SUCCESS: {
    label: "Success",
    classes: "bg-emerald-50 text-emerald-800 ring-1 ring-inset ring-emerald-200",
    dot: "bg-emerald-500",
  },
  FAILED: {
    label: "Failed",
    classes: "bg-rose-50 text-rose-800 ring-1 ring-inset ring-rose-200",
    dot: "bg-rose-500",
  },
  SKIPPED: {
    label: "Skipped",
    classes: "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200",
    dot: "bg-slate-400",
  },
};

export const UNKNOWN_CASE_META: StatusBadgeMeta = {
  label: "Unknown",
  classes: "bg-slate-100 text-slate-700 ring-1 ring-inset ring-slate-200",
  dot: "bg-slate-400",
};

export const UNKNOWN_ACTION_META: StatusBadgeMeta = UNKNOWN_CASE_META;

export function getCaseStatusMeta(status: string): StatusBadgeMeta {
  if (status in CASE_STATUS_META) {
    return CASE_STATUS_META[status as RecoveryCaseStatus];
  }
  return { ...UNKNOWN_CASE_META, label: status || "Unknown" };
}

export function getActionStatusMeta(status: string): StatusBadgeMeta {
  if (status in ACTION_STATUS_META) {
    return ACTION_STATUS_META[status]!;
  }
  return { ...UNKNOWN_ACTION_META, label: status || "Unknown" };
}

// ---------------------------------------------------------------------------
// Audit timeline friendly labels
// ---------------------------------------------------------------------------

export type AuditTone = "neutral" | "info" | "success" | "warn" | "danger";

export interface AuditLabel {
  title: string;
  tone: AuditTone;
}

export const AUDIT_LABEL_MAP: Record<string, AuditLabel> = {
  "webhook.received": {
    title: "Payment Failed",
    tone: "danger",
  },
  "webhook.normalized": {
    title: "Event Normalized",
    tone: "neutral",
  },
  "webhook.duplicate": {
    title: "Duplicate Webhook Skipped",
    tone: "neutral",
  },
  "webhook.signature_invalid": {
    title: "Invalid Webhook Signature",
    tone: "danger",
  },
  "webhook.rejected": {
    title: "Webhook Rejected",
    tone: "warn",
  },
  "webhook.pipeline_triggered": {
    title: "Recovery Pipeline Triggered",
    tone: "info",
  },
  "webhook.pipeline_deferred": {
    title: "Recovery Pipeline Deferred",
    tone: "neutral",
  },
  "recovery.case_created": {
    title: "Recovery Case Created",
    tone: "info",
  },
  "policy.decision": {
    title: "Policy Decision",
    tone: "info",
  },
  "safeguard.decision": {
    title: "Safeguards Check",
    tone: "info",
  },
  "execution.attempted": {
    title: "Execution Attempted",
    tone: "neutral",
  },
  "execution.succeeded": {
    title: "Execution Succeeded",
    tone: "success",
  },
  "execution.failed": {
    title: "Execution Failed",
    tone: "danger",
  },
  "execution.blocked": {
    title: "Execution Blocked",
    tone: "warn",
  },
  "execution.duplicate": {
    title: "Duplicate Execution Skipped",
    tone: "neutral",
  },
  "execution.skipped": {
    title: "Execution Skipped",
    tone: "warn",
  },
  "case.approved": {
    title: "Case Approved",
    tone: "success",
  },
  "case.approval_rejected": {
    title: "Approval Rejected",
    tone: "warn",
  },
  "outcome.recorded": {
    title: "Outcome Recorded",
    tone: "info",
  },
  "pipeline.error": {
    title: "Pipeline Error",
    tone: "danger",
  },
};

export const TONE_META: Record<AuditTone, { dot: string; ring: string; text: string }> = {
  neutral: {
    dot: "bg-slate-400",
    ring: "ring-slate-200",
    text: "text-slate-700",
  },
  info: {
    dot: "bg-blue-500",
    ring: "ring-blue-200",
    text: "text-blue-800",
  },
  success: {
    dot: "bg-emerald-500",
    ring: "ring-emerald-200",
    text: "text-emerald-800",
  },
  warn: {
    dot: "bg-amber-500",
    ring: "ring-amber-200",
    text: "text-amber-800",
  },
  danger: {
    dot: "bg-rose-500",
    ring: "ring-rose-200",
    text: "text-rose-800",
  },
};

export function getAuditLabel(eventType: string): AuditLabel {
  return (
    AUDIT_LABEL_MAP[eventType] ?? {
      title: eventType || "Audit Event",
      tone: "neutral",
    }
  );
}
