// Recovery Cases — filterable + paginated list.
//
// Owns its own fetch on mount and when filters change. Reports row-click
// via onSelectCase. Polling is intentionally absent — the parent triggers
// refresh by changing `refreshKey` (after approve/execute).

import { useEffect, useMemo, useState } from "react";
import { listRecoveryCases } from "../api";
import { formatINR, formatPercent, formatTimestampShort } from "../format";
import {
  ACTION_LABELS,
  type CaseSummary,
  type RecoveryActionType,
  type RecoveryCaseStatus,
  RECOVERABLE_ACTIONS,
  STATUS_LABELS,
} from "../types";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  Section,
  StatusBadge,
} from "./primitives";

interface RecoveryCasesProps {
  refreshKey: number;
  onSelectCase: (caseId: string) => void;
}

const STATUS_FILTERS: ReadonlyArray<RecoveryCaseStatus | "all"> = [
  "all",
  "pending",
  "approved",
  "blocked",
  "executing",
  "succeeded",
  "failed",
  "rejected",
];

const PAGE_SIZE = 20;

export function RecoveryCases({ refreshKey, onSelectCase }: RecoveryCasesProps) {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<RecoveryCaseStatus | "all">(
    "all",
  );
  const [actionFilter, setActionFilter] = useState<RecoveryActionType | "">("");
  const [page, setPage] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listRecoveryCases({ limit: 200 })
      .then((rows) => {
        if (!cancelled) {
          setCases(rows);
          setLoading(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const filtered = useMemo(() => {
    return cases.filter((c) => {
      if (statusFilter !== "all" && c.status !== statusFilter) return false;
      if (actionFilter && c.recommended_action !== actionFilter) return false;
      return true;
    });
  }, [cases, statusFilter, actionFilter]);

  const pageStart = page * PAGE_SIZE;
  const paged = filtered.slice(pageStart, pageStart + PAGE_SIZE);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));

  // Reset to page 0 when filters change.
  useEffect(() => {
    setPage(0);
  }, [statusFilter, actionFilter]);

  const actionsAvailable = useMemo(() => {
    const set = new Set<RecoveryActionType>();
    cases.forEach((c) => {
      if (c.recommended_action) {
        const candidate = c.recommended_action as RecoveryActionType;
        if (RECOVERABLE_ACTIONS.has(candidate)) set.add(candidate);
      }
    });
    return Array.from(set).sort();
  }, [cases]);

  const activeFilters =
    statusFilter !== "all" || actionFilter !== ""
      ? `Filtered by: ${statusFilter !== "all" ? STATUS_LABELS[statusFilter] : "all statuses"}${
          actionFilter
            ? ` · ${ACTION_LABELS[actionFilter as RecoveryActionType] ?? actionFilter}`
            : ""
        }`
      : null;

  return (
    <Section
      title="Recovery Cases"
      subtitle={`${filtered.length} of ${cases.length} case${cases.length === 1 ? "" : "s"}${filtered.length !== cases.length ? " (filtered)" : ""}`}
      actions={
        <div className="flex items-center gap-2">
          {activeFilters ? (
            <button
              type="button"
              onClick={() => {
                setStatusFilter("all");
                setActionFilter("");
              }}
              className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200"
            >
              Clear filters
            </button>
          ) : null}
        </div>
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1.5">
          {STATUS_FILTERS.map((s) => {
            const active = statusFilter === s;
            return (
              <button
                key={s}
                type="button"
                onClick={() => setStatusFilter(s)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                  active
                    ? "bg-indigo-600 text-white shadow-soft"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {s === "all" ? "All" : STATUS_LABELS[s]}
              </button>
            );
          })}
        </div>
        <select
          value={actionFilter}
          onChange={(e) =>
            setActionFilter(e.target.value as RecoveryActionType | "")
          }
          className="ml-auto rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-soft focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        >
          <option value="">All actions</option>
          {actionsAvailable.map((a) => (
            <option key={a} value={a}>
              {ACTION_LABELS[a] ?? a}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <LoadingState rows={6} />
      ) : error ? (
        <ErrorState message={error} />
      ) : cases.length === 0 ? (
        <EmptyState
          title="No recovery cases yet"
          description="Webhook ingestion is pending. Once a payment failure is received, recovery cases will appear here."
        />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="No cases match the selected filters"
          description="Try clearing the active filters to see all recovery cases."
          action={
            <button
              type="button"
              onClick={() => {
                setStatusFilter("all");
                setActionFilter("");
              }}
              className="rounded-md bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-700"
            >
              Clear filters
            </button>
          }
        />
      ) : (
        <>
          <div className="overflow-hidden rounded-xl border border-slate-200">
            <table className="min-w-full divide-y divide-slate-100 text-sm">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-2.5">Case ID</th>
                  <th className="px-4 py-2.5">Amount</th>
                  <th className="px-4 py-2.5">Risk</th>
                  <th className="px-4 py-2.5">Recommended Action</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {paged.map((c) => (
                  <tr
                    key={c.id}
                    onClick={() => onSelectCase(c.id)}
                    className="cursor-pointer bg-white transition-colors hover:bg-indigo-50/40"
                  >
                    <td className="px-4 py-2.5 font-mono text-xs text-slate-600">
                      {c.id.slice(0, 12)}
                    </td>
                    <td className="px-4 py-2.5 tabular-nums font-medium text-slate-900">
                      {formatINR(c.amount)}
                    </td>
                    <td className="px-4 py-2.5 tabular-nums text-slate-700">
                      {formatPercent(c.recovery_probability)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {c.recommended_action
                        ? ACTION_LABELS[c.recommended_action as RecoveryActionType] ??
                          c.recommended_action
                        : "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={c.status} size="sm" />
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500">
                      {formatTimestampShort(c.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 ? (
            <div className="mt-3 flex items-center justify-between text-xs text-slate-600">
              <p>
                Page {page + 1} of {totalPages} · {filtered.length} case
                {filtered.length === 1 ? "" : "s"}
              </p>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="rounded-md border border-slate-200 bg-white px-3 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-50"
                >
                  Prev
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setPage((p) => Math.min(totalPages - 1, p + 1))
                  }
                  disabled={page >= totalPages - 1}
                  className="rounded-md border border-slate-200 bg-white px-3 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-50"
                >
                  Next
                </button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </Section>
  );
}
