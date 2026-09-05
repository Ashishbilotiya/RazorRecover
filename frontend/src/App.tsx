// App shell — header + tagline + status dot, then renders DashboardPage.
//
// Backend health is checked once on mount for the status indicator only.
// A failure here does NOT block the dashboard — individual sections show
// their own error states if fetches fail.

import { useEffect, useState } from "react";
import { API_BASE } from "./api";
import { DashboardPage } from "./pages/DashboardPage";

type HealthState = "unknown" | "ok" | "down";

export default function App() {
  const [health, setHealth] = useState<HealthState>("unknown");

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/health`)
      .then((res) => {
        if (cancelled) return;
        setHealth(res.ok ? "ok" : "down");
      })
      .catch(() => {
        if (cancelled) return;
        setHealth("down");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-4 sm:px-6 lg:px-8">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-slate-900">
              RazorRecover
            </h1>
            <p className="text-xs text-slate-500">
              AI-powered revenue recovery · Razorpay Test Mode
            </p>
          </div>
          <HealthBadge state={health} />
        </div>
      </header>
      <DashboardPage />
      <footer className="border-t border-slate-200 bg-white py-4">
        <p className="mx-auto max-w-7xl px-4 text-center text-[11px] text-slate-400 sm:px-6 lg:px-8">
          Built for the Razorpay Buildathon 2026 — Track 03 · Test mode only,
          no real money moves.
        </p>
      </footer>
    </div>
  );
}

function HealthBadge({ state }: { state: HealthState }) {
  const label =
    state === "ok" ? "Backend online" : state === "down" ? "Backend offline" : "Checking…";
  const dot =
    state === "ok"
      ? "bg-emerald-500"
      : state === "down"
        ? "bg-rose-500"
        : "bg-amber-500 animate-pulse";
  const ring =
    state === "ok"
      ? "ring-emerald-200"
      : state === "down"
        ? "ring-rose-200"
        : "ring-amber-200";
  return (
    <div
      className={`flex items-center gap-2 rounded-full bg-white px-3 py-1.5 text-xs font-medium text-slate-700 ring-1 ring-inset ${ring}`}
      title={`Backend at ${API_BASE}`}
    >
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      {label}
    </div>
  );
}
