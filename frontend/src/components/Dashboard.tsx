// Dashboard — top 4 KPI cards + Recovery Performance bars.
//
// All numbers come from props (AnalyticsOverview) fetched by the parent.
// Never invent figures here.

import { useEffect, useState } from "react";
import {
  formatINRCompact,
  formatPercent,
  formatRelative,
} from "../format";
import { ErrorState, LoadingState, Section, StatCard } from "./primitives";
import { getAnalytics } from "../api";
import type { AnalyticsOverview } from "../types";

interface DashboardProps {
  /** Injected by the parent. When it changes, the component re-fetches. */
  refreshKey: number;
}

export function Dashboard({ refreshKey }: DashboardProps) {
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAnalytics()
      .then((res) => {
        if (!cancelled) {
          setData(res);
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

  if (loading) return <LoadingState variant="card" />;
  if (error || !data)
    return (
      <ErrorState
        title="Couldn't load analytics"
        message={error ?? "Unknown error"}
      />
    );

  return (
    <div className="space-y-6">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Revenue at Risk"
          value={formatINRCompact(data.revenue_at_risk)}
          hint={`${data.total_failed_transactions} failed payments`}
          accent="amber"
        />
        <StatCard
          label="Revenue Recovered"
          value={formatINRCompact(data.revenue_recovered)}
          hint={`${formatPercent(data.recovery_rate)} recovery rate`}
          accent="emerald"
        />
        <StatCard
          label="Recovery Rate"
          value={formatPercent(data.recovery_rate)}
          hint={`of ${formatINRCompact(data.revenue_targeted)} targeted`}
          accent="indigo"
        />
        <StatCard
          label="Recovery Cases"
          value={String(data.recovery_cases)}
          hint={`${data.successful_actions} succeeded · ${data.failed_actions} failed`}
          accent="blue"
        />
      </div>

      <Section
        title="Recovery Performance"
        subtitle="Live aggregate of at-risk vs recovered revenue and intervention outcomes."
      >
        <div className="grid gap-6 lg:grid-cols-2">
          <BarGroup
            title="Revenue at Risk vs Recovered"
            rows={[
              {
                label: "At risk",
                value: data.revenue_at_risk,
                color: "bg-amber-500",
              },
              {
                label: "Recovered",
                value: data.revenue_recovered,
                color: "bg-emerald-500",
              },
            ]}
            max={Math.max(data.revenue_at_risk, data.revenue_recovered, 1)}
            formatter={formatINRCompact}
          />

          <BarGroup
            title="Intervention Outcomes"
            rows={[
              {
                label: `Successful (${data.successful_actions})`,
                value: data.successful_actions,
                color: "bg-emerald-500",
              },
              {
                label: `Failed (${data.failed_actions})`,
                value: data.failed_actions,
                color: "bg-rose-500",
              },
              {
                label: `Blocked (${data.blocked_actions})`,
                value: data.blocked_actions,
                color: "bg-orange-500",
              },
            ]}
            max={Math.max(
              data.successful_actions,
              data.failed_actions,
              data.blocked_actions,
              1,
            )}
            formatter={(n) => String(n)}
          />
        </div>

        <p className="mt-4 text-[11px] text-slate-400">
          Last refreshed {formatRelative(new Date().toISOString())}.
        </p>
      </Section>
    </div>
  );
}

interface BarRow {
  label: string;
  value: number;
  color: string;
}

interface BarGroupProps {
  title: string;
  rows: BarRow[];
  max: number;
  formatter: (n: number) => string;
}

function BarGroup({ title, rows, max, formatter }: BarGroupProps) {
  return (
    <div>
      <h3 className="mb-3 text-sm font-medium text-slate-700">{title}</h3>
      <div className="space-y-3">
        {rows.map((row) => {
          const pct = max > 0 ? Math.min(100, (row.value / max) * 100) : 0;
          return (
            <div key={row.label}>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-xs font-medium text-slate-600">
                  {row.label}
                </span>
                <span className="text-xs font-semibold tabular-nums text-slate-900">
                  {formatter(row.value)}
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className={`h-full ${row.color} transition-all duration-500`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
