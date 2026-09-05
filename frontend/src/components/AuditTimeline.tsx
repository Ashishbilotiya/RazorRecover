// Audit Timeline — vertical list of audit events for one case.
//
// Renders event_type → friendly title + tone mapping. Surfaces a small,
// curated subset of `metadata` keys. Never invents values; never displays
// chain-of-thought style fields.

import { useEffect, useState } from "react";
import { getAudit } from "../api";
import type { AuditEventOut } from "../types";
import { getAuditLabel, TONE_META } from "../badges";
import { formatINR, formatPercent, formatRelative } from "../format";
import { EmptyState, ErrorState, Skeleton } from "./primitives";

interface AuditTimelineProps {
  caseId: string;
  refreshKey: number;
}

export function AuditTimeline({ caseId, refreshKey }: AuditTimelineProps) {
  const [events, setEvents] = useState<AuditEventOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getAudit(caseId)
      .then((rows) => {
        if (!cancelled) {
          setEvents(rows);
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
  }, [caseId, refreshKey]);

  if (loading) {
    return (
      <div className="space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex gap-3">
            <Skeleton className="h-3 w-3 rounded-full" />
            <Skeleton className="h-10 flex-1 rounded-lg" />
          </div>
        ))}
      </div>
    );
  }
  if (error) return <ErrorState message={error} />;
  if (events.length === 0)
    return (
      <EmptyState
        title="No audit events yet"
        description="Audit events are recorded as the system processes the case."
      />
    );

  return (
    <ol className="relative space-y-5 border-l border-slate-200 pl-6">
      {events.map((evt) => {
        const label = getAuditLabel(evt.event_type);
        const tone = TONE_META[label.tone];
        const curated = curateMetadata(evt);
        return (
          <li key={evt.id} className="relative">
            <span
              className={`absolute -left-[31px] top-1.5 h-3 w-3 rounded-full ring-4 ring-white ${tone.dot}`}
              aria-hidden
            />
            <div className="flex items-baseline justify-between gap-2">
              <p className={`text-sm font-semibold ${tone.text}`}>
                {label.title}
              </p>
              <time className="shrink-0 text-xs text-slate-400">
                {formatRelative(evt.created_at)}
              </time>
            </div>
            <p className="mt-0.5 text-xs text-slate-500">
              {evt.actor}
              {evt.decision ? (
                <>
                  {" · "}
                  <span className="font-medium text-slate-700">
                    {evt.decision}
                  </span>
                </>
              ) : null}
            </p>
            {evt.reason ? (
              <p className="mt-1 text-xs text-slate-600">{evt.reason}</p>
            ) : null}
            {curated.length > 0 ? (
              <ul className="mt-2 space-y-0.5 rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-600">
                {curated.map(([k, v]) => (
                  <li key={k} className="flex items-baseline justify-between gap-2">
                    <span className="text-slate-500">{k}</span>
                    <span className="font-mono text-slate-700">{v}</span>
                  </li>
                ))}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

// Render a curated, safe subset of metadata. We deliberately exclude any
// key whose value is a long free-form string (potential chain-of-thought
// leak from the LLM) and never render nested objects.
const SAFE_KEYS: ReadonlySet<string> = new Set([
  "recovery_probability",
  "revenue_at_risk",
  "policy_rule",
  "policy_verdict",
  "amount",
  "amount_recovered",
  "external_reference",
  "error_code",
  "action",
  "verdict",
  "attempt_number",
  "case_id",
  "approved_at",
]);

function curateMetadata(evt: AuditEventOut): Array<[string, string]> {
  const md = evt.metadata;
  if (!md) return [];
  const out: Array<[string, string]> = [];
  for (const [k, raw] of Object.entries(md)) {
    if (!SAFE_KEYS.has(k)) continue;
    if (raw === null || raw === undefined) continue;
    if (typeof raw === "object") continue;
    if (typeof raw === "string" && raw.length > 80) continue;
    if (k === "recovery_probability" && typeof raw === "number") {
      out.push([k, formatPercent(raw)]);
    } else if (k === "revenue_at_risk" && typeof raw === "number") {
      out.push([k, formatINR(raw)]);
    } else if (k === "amount" && typeof raw === "number") {
      out.push([k, formatINR(raw)]);
    } else if (k === "amount_recovered" && typeof raw === "number") {
      out.push([k, formatINR(raw)]);
    } else {
      out.push([k, String(raw)]);
    }
  }
  return out;
}
