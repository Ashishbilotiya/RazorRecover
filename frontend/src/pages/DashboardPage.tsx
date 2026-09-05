// DashboardPage — composes the four sections + opens the CaseDetail drawer.
//
// Owns the cross-cutting "open a case" state and the refreshKey counter that
// increments after every approve/execute mutation. Children re-fetch on
// refreshKey change; that is the entire refresh strategy (CLAUDE.md rule 12).

import { useCallback, useState } from "react";
import { Dashboard } from "../components/Dashboard";
import { RecoveryCases } from "../components/RecoveryCases";
import { TransactionTable } from "../components/TransactionTable";
import { CaseDetail } from "../components/CaseDetail";

export function DashboardPage() {
  const [activeCaseId, setActiveCaseId] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const bumpRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  return (
    <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="space-y-6">
        <Dashboard refreshKey={refreshKey} />
        <RecoveryCases refreshKey={refreshKey} onSelectCase={setActiveCaseId} />
        <TransactionTable refreshKey={refreshKey} status="failed" />
      </div>

      {activeCaseId ? (
        <CaseDetail
          caseId={activeCaseId}
          onClose={() => setActiveCaseId(null)}
          onChange={bumpRefresh}
        />
      ) : null}
    </main>
  );
}
