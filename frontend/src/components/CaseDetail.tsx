// CaseDetail — right-side drawer for one recovery case.
//
// Owns fetch of /api/recovery/cases/{id} + /api/audit/{id}. Approve /
// Execute are gated on case.status and pass through the backend's policy
// + safeguards + executor chain (CLAUDE.md §21).

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  approveRecovery,
  executeRecovery,
  getRecoveryCase,
  NotFoundError,
  StateConflictError,
} from "../api";
import type { CaseDetail as CaseDetailModel, ExecutionResponse } from "../types";
import {
  ACTION_LABELS,
  ROOT_CAUSE_LABELS,
  type RecoveryActionType,
  type RecoveryCaseStatus,
  type RootCauseCategory,
} from "../types";
import {
  formatINR,
  formatPercent,
  formatTimestampShort,
  shortId,
} from "../format";
import {
  ErrorState,
  Modal,
  Section,
  Skeleton,
  StatusBadge,
} from "./primitives";
import { AuditTimeline } from "./AuditTimeline";

interface CaseDetailProps {
  caseId: string;
  onClose: () => void;
  /** Called after a successful approve or execute so the parent can refetch. */
  onChange: () => void;
}

export function CaseDetail({ caseId, onClose, onChange }: CaseDetailProps) {
  const [data, setData] = useState<CaseDetailModel | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [acting, setActing] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  // Confirmation modal state.
  const [confirmApprove, setConfirmApprove] = useState(false);
  const [confirmExecute, setConfirmExecute] = useState(false);

  // Result modal state — shown after execute completes.
  const [executionResult, setExecutionResult] = useState<ExecutionResponse | null>(
    null,
  );

  const fetchCase = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const detail = await getRecoveryCase(caseId);
      setData(detail);
    } catch (err) {
      if (err instanceof NotFoundError) {
        setError("This recovery case was not found.");
      } else {
        setError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    void fetchCase();
  }, [fetchCase, refreshKey]);

  // Escape closes drawer.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Lock body scroll while open.
  useEffect(() => {
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previous;
    };
  }, []);

  const canApprove =
    data !== null && (data.status === "pending" || data.status === "blocked");
  const canExecute = data !== null && data.status === "approved";

  async function handleApprove() {
    if (!data) return;
    setActing(true);
    setActionError(null);
    try {
      await approveRecovery(data.id);
      setConfirmApprove(false);
      setRefreshKey((k) => k + 1);
      onChange();
    } catch (err) {
      if (err instanceof StateConflictError) {
        setActionError(
          err.detail ?? "Case cannot be approved in its current state.",
        );
      } else {
        setActionError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setActing(false);
    }
  }

  async function handleExecute() {
    if (!data) return;
    setActing(true);
    setActionError(null);
    try {
      const result = await executeRecovery(data.id);
      setConfirmExecute(false);
      setExecutionResult(result);
      setRefreshKey((k) => k + 1);
      onChange();
    } catch (err) {
      if (err instanceof StateConflictError) {
        setActionError(
          err.detail ?? "Case cannot be executed in its current state.",
        );
      } else {
        setActionError(err instanceof Error ? err.message : String(err));
      }
    } finally {
      setActing(false);
    }
  }

  const actionType = useMemo<RecoveryActionType | null>(() => {
    if (!data?.recommended_action) return null;
    return data.recommended_action as RecoveryActionType;
  }, [data]);

  const rootCause = useMemo<RootCauseCategory | null>(() => {
    if (!data?.root_cause) return null;
    return data.root_cause as RootCauseCategory;
  }, [data]);

  return (
    <>
      <div className="fixed inset-0 z-30 bg-slate-900/40 animate-fadein" onClick={onClose} />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label="Recovery case detail"
        className="fixed right-0 top-0 z-40 flex h-full w-full flex-col bg-white shadow-drawer md:w-[680px] animate-slidein"
      >
        <header className="flex items-center justify-between border-b border-slate-200 px-6 py-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">
              Recovery Case
            </p>
            <p className="mt-0.5 font-mono text-sm text-slate-900">
              {shortId(caseId, 16)}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
            aria-label="Close case detail"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              className="h-4 w-4"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 6l12 12M6 18L18 6" />
            </svg>
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-6 py-5">
          {loading ? (
            <div className="space-y-4">
              <Skeleton className="h-6 w-1/2" />
              <Skeleton className="h-32 w-full rounded-2xl" />
              <Skeleton className="h-32 w-full rounded-2xl" />
              <Skeleton className="h-32 w-full rounded-2xl" />
            </div>
          ) : error ? (
            <ErrorState message={error} onRetry={() => setRefreshKey((k) => k + 1)} />
          ) : data ? (
            <div className="space-y-5">
              <Section title="Transaction">
                <dl className="grid grid-cols-2 gap-4 text-sm">
                  <Field label="Amount">
                    <span className="text-base font-semibold tabular-nums text-slate-900">
                      {formatINR(data.amount)}
                    </span>
                  </Field>
                  <Field label="Status">
                    <StatusBadge
                      status={data.status}
                      kind="case"
                    />
                  </Field>
                  <Field label="Recovery Probability">
                    <span className="font-semibold text-slate-900">
                      {formatPercent(data.recovery_probability)}
                    </span>
                  </Field>
                  <Field label="Revenue at Risk">
                    <span className="tabular-nums text-slate-900">
                      {formatINR(data.revenue_at_risk)}
                    </span>
                  </Field>
                  <Field label="Failure Reason">
                    <span className="text-slate-700">
                      {data.transaction?.failure_reason ?? "—"}
                    </span>
                  </Field>
                  <Field label="Payment Method">
                    <span className="text-slate-700">
                      {data.transaction?.payment_method ?? "—"}
                    </span>
                  </Field>
                  <Field label="Razorpay Payment ID">
                    <span className="font-mono text-xs text-slate-700">
                      {shortId(data.transaction?.razorpay_payment_id ?? "", 18)}
                    </span>
                  </Field>
                  <Field label="Created">
                    <span className="text-slate-700">
                      {formatTimestampShort(data.created_at)}
                    </span>
                  </Field>
                </dl>
              </Section>

              <Section title="AI Analysis">
                <dl className="grid grid-cols-2 gap-4 text-sm">
                  <Field label="Root Cause">
                    <span className="text-slate-700">
                      {rootCause
                        ? ROOT_CAUSE_LABELS[rootCause] ?? data.root_cause
                        : data.root_cause ?? "—"}
                    </span>
                  </Field>
                  <Field label="Confidence">
                    <span className="font-semibold text-slate-900">
                      {formatPercent(data.confidence)}
                    </span>
                  </Field>
                  <Field label="Recommended Action">
                    <span className="text-slate-700">
                      {actionType
                        ? ACTION_LABELS[actionType] ?? data.recommended_action
                        : data.recommended_action ?? "—"}
                    </span>
                  </Field>
                </dl>
              </Section>

              <Section
                title="Audit Timeline"
                subtitle="Every decision the system made for this case."
              >
                <AuditTimeline caseId={caseId} refreshKey={refreshKey} />
              </Section>

              <Section title="Recovery Action">
                {data.actions.length === 0 ? (
                  <p className="text-sm text-slate-500">
                    No recovery action executed yet.
                  </p>
                ) : (
                  <div className="space-y-2 text-sm">
                    {data.actions.map((a) => (
                      <div
                        key={a.id}
                        className="flex items-center justify-between rounded-lg border border-slate-100 bg-slate-50/60 px-3 py-2"
                      >
                        <div>
                          <p className="font-medium text-slate-700">
                            {a.action_type}
                          </p>
                          {a.reason ? (
                            <p className="text-xs text-slate-500">{a.reason}</p>
                          ) : null}
                        </div>
                        <StatusBadge status={a.status} kind="action" size="sm" />
                      </div>
                    ))}
                  </div>
                )}
              </Section>
            </div>
          ) : null}
        </div>

        {data && (canApprove || canExecute) ? (
          <footer className="border-t border-slate-200 bg-slate-50 px-6 py-3">
            {actionError ? (
              <p className="mb-2 text-xs text-rose-600">{actionError}</p>
            ) : null}
            <div className="flex flex-wrap items-center justify-end gap-2">
              {canApprove ? (
                <button
                  type="button"
                  onClick={() => setConfirmApprove(true)}
                  disabled={acting}
                  className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-soft hover:bg-slate-50 disabled:opacity-50"
                >
                  Approve for execution
                </button>
              ) : null}
              {canExecute ? (
                <button
                  type="button"
                  onClick={() => setConfirmExecute(true)}
                  disabled={acting}
                  className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white shadow-soft hover:bg-indigo-700 disabled:opacity-50"
                >
                  Execute recovery
                </button>
              ) : null}
            </div>
            {canApprove ? (
              <p className="mt-2 text-right text-[11px] text-slate-500">
                Approving allows execution. It does NOT bypass safeguards.
              </p>
            ) : null}
          </footer>
        ) : null}
      </aside>

      <Modal
        open={confirmApprove}
        onClose={() => !acting && setConfirmApprove(false)}
        title="Approve this recovery case?"
        size="sm"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setConfirmApprove(false)}
              disabled={acting}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleApprove}
              disabled={acting}
              className="rounded-md bg-emerald-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
            >
              {acting ? "Approving…" : "Approve"}
            </button>
          </div>
        }
      >
        <p className="text-sm text-slate-700">
          The case will move to <strong>Approved</strong>. It can then be executed
          through the policy + safeguards + executor pipeline.
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Approving does NOT bypass safeguards — the executor will re-validate
          every rule before any financial action.
        </p>
      </Modal>

      <Modal
        open={confirmExecute}
        onClose={() => !acting && setConfirmExecute(false)}
        title="Confirm recovery execution"
        size="md"
        footer={
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setConfirmExecute(false)}
              disabled={acting}
              className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleExecute}
              disabled={acting}
              className="rounded-md bg-indigo-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-indigo-700 disabled:opacity-50"
            >
              {acting ? "Executing…" : "Execute"}
            </button>
          </div>
        }
      >
        {data ? (
          <dl className="space-y-2 text-sm">
            <Row label="Amount">
              <span className="font-semibold text-slate-900 tabular-nums">
                {formatINR(data.amount)}
              </span>
            </Row>
            <Row label="Action">
              <span className="font-mono text-slate-900">
                {data.recommended_action ?? "—"}
              </span>
            </Row>
            <Row label="Recovery probability">
              <span className="tabular-nums text-slate-900">
                {formatPercent(data.recovery_probability)}
              </span>
            </Row>
            <Row label="Expected recovery">
              <span className="tabular-nums text-slate-900">
                {formatINR(data.revenue_at_risk)}
              </span>
            </Row>
          </dl>
        ) : null}
        <p className="mt-3 text-xs text-slate-500">
          Backend will re-validate policy + safeguards before any Razorpay call.
          This is a Test-Mode action — no real funds move.
        </p>
      </Modal>

      <Modal
        open={executionResult !== null}
        onClose={() => setExecutionResult(null)}
        title={
          executionResult?.status === "succeeded"
            ? "Execution Successful"
            : executionResult?.status === "failed"
              ? "Execution Failed"
              : "Execution Started"
        }
        size="md"
        footer={
          <div className="flex justify-end">
            <button
              type="button"
              onClick={() => setExecutionResult(null)}
              className="rounded-md bg-slate-700 px-3 py-1.5 text-sm font-semibold text-white hover:bg-slate-800"
            >
              Close
            </button>
          </div>
        }
      >
        {executionResult ? (
          <ExecutionResultPanel result={executionResult} />
        ) : null}
      </Modal>
    </>
  );
}

function ExecutionResultPanel({ result }: { result: ExecutionResponse }) {
  const isSuccess = result.status === "succeeded";
  const isFailed = result.status === "failed";
  const panelClass = isSuccess
    ? "border-emerald-200 bg-emerald-50"
    : isFailed
      ? "border-rose-200 bg-rose-50"
      : "border-blue-200 bg-blue-50";
  const titleClass = isSuccess
    ? "text-emerald-800"
    : isFailed
      ? "text-rose-800"
      : "text-blue-800";
  const footerClass = isSuccess
    ? "text-emerald-700"
    : isFailed
      ? "text-rose-700"
      : "text-blue-700";

  return (
    <div className="space-y-3">
      <div className={`rounded-xl border ${panelClass} px-4 py-3 text-sm`}>
        <p className={`font-semibold ${titleClass}`}>
          {isSuccess
            ? "Recovery executed successfully"
            : isFailed
              ? "Recovery execution failed"
              : "Execution started"}
        </p>
        {result.already_executed ? (
          <p className={`mt-0.5 text-xs ${footerClass}`}>
            This case was already executed; the original outcome is shown.
          </p>
        ) : null}
      </div>
      <dl className="space-y-2 text-sm">
        <Row label="Status">
          <StatusBadge
            status={
              result.status === "succeeded"
                ? "succeeded"
                : result.status === "failed"
                  ? "failed"
                  : "executing"
            }
          />
        </Row>
        <Row label="Action">
          <span className="font-mono text-slate-900">{result.action_type ?? "—"}</span>
        </Row>
        {result.status !== "executing" ? (
          <Row label="Amount recovered">
            <span className="font-semibold tabular-nums text-slate-900">
              {formatINR(result.amount_recovered)}
            </span>
          </Row>
        ) : null}
        {result.external_reference ? (
          <Row label="Reference">
            <span className="font-mono text-xs text-slate-700">
              {result.external_reference}
            </span>
          </Row>
        ) : null}
        {result.error_code ? (
          <Row label="Error code">
            <span className="font-mono text-xs text-rose-700">
              {result.error_code}
            </span>
          </Row>
        ) : null}
        {result.message ? (
          <Row label="Details">
            <span className="text-xs text-slate-600">{result.message}</span>
          </Row>
        ) : null}
        <Row label="Idempotency key">
          <span className="font-mono text-[11px] text-slate-600">
            {result.idempotency_key}
          </span>
        </Row>
      </dl>
      <p className="text-[11px] text-slate-400">
        (Test-mode amount, no real funds moved.)
      </p>
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm">{children}</dd>
    </div>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-dashed border-slate-100 pb-2 last:border-b-0 last:pb-0">
      <dt className="text-xs font-medium uppercase tracking-wider text-slate-500">
        {label}
      </dt>
      <dd className="text-right text-sm">{children}</dd>
    </div>
  );
}

// Suppress unused import lint warnings if certain helpers are only used by
// the data renderers above. Keeping the import side-effect-free here.
const _unused: RecoveryCaseStatus | undefined = undefined;
void _unused;
