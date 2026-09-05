// TransactionTable — compact list of recent transactions.
//
// TransactionSummary.amount is in PAISE — we divide by 100 before display.

import { useEffect, useMemo, useState } from "react";
import { listTransactions } from "../api";
import { formatPaise, formatTimestampShort } from "../format";
import type { TransactionSummary } from "../types";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  Section,
  StatusBadge,
} from "./primitives";

interface TransactionTableProps {
  refreshKey: number;
  /** Optional status filter; defaults to "failed" since that's the relevant slice. */
  status?: string;
}

const PAGE_SIZE = 10;

export function TransactionTable({
  refreshKey,
  status = "failed",
}: TransactionTableProps) {
  const [rows, setRows] = useState<TransactionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listTransactions({ status, limit: 200 })
      .then((res) => {
        if (!cancelled) {
          setRows(res);
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
  }, [refreshKey, status]);

  const paged = useMemo(() => {
    const start = page * PAGE_SIZE;
    return rows.slice(start, start + PAGE_SIZE);
  }, [rows, page]);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));

  return (
    <Section
      title={`Recent ${status === "failed" ? "Failed" : ""} Transactions`.trim()}
      subtitle={`${rows.length} ${status === "failed" ? "failed payment" : "transaction"}${rows.length === 1 ? "" : "s"}`}
    >
      {loading ? (
        <LoadingState rows={5} />
      ) : error ? (
        <ErrorState message={error} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No transactions yet"
          description="Once a payment event is received from Razorpay, transactions will appear here."
        />
      ) : (
        <>
          <div className="overflow-hidden rounded-xl border border-slate-200">
            <table className="min-w-full divide-y divide-slate-100 text-sm">
              <thead className="bg-slate-50">
                <tr className="text-left text-xs font-semibold uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-2.5">Payment</th>
                  <th className="px-4 py-2.5">Amount</th>
                  <th className="px-4 py-2.5">Method</th>
                  <th className="px-4 py-2.5">Status</th>
                  <th className="px-4 py-2.5">Failure</th>
                  <th className="px-4 py-2.5">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {paged.map((t) => (
                  <tr key={t.id} className="bg-white">
                    <td className="px-4 py-2.5 font-mono text-xs text-slate-600">
                      {t.razorpay_payment_id.length > 18
                        ? `${t.razorpay_payment_id.slice(0, 18)}…`
                        : t.razorpay_payment_id}
                    </td>
                    <td className="px-4 py-2.5 tabular-nums font-medium text-slate-900">
                      {formatPaise(t.amount)}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">
                      {t.payment_method ?? "—"}
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusBadge status={t.status} kind="case" size="sm" />
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500">
                      {t.failure_reason ?? "—"}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate-500">
                      {formatTimestampShort(t.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 ? (
            <div className="mt-3 flex items-center justify-end gap-1 text-xs text-slate-600">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(0, p - 1))}
                disabled={page === 0}
                className="rounded-md border border-slate-200 bg-white px-3 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-50"
              >
                Prev
              </button>
              <span className="px-2">
                {page + 1} / {totalPages}
              </span>
              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                disabled={page >= totalPages - 1}
                className="rounded-md border border-slate-200 bg-white px-3 py-1 font-medium disabled:cursor-not-allowed disabled:opacity-40 hover:bg-slate-50"
              >
                Next
              </button>
            </div>
          ) : null}
        </>
      )}
    </Section>
  );
}
