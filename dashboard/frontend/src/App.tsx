import { useCallback, useEffect, useState } from "react";
import { api, type Status } from "./api";
import { timeAgo } from "./format";
import { ActionsPanel } from "./components/ActionsPanel";
import { ActivityChart } from "./components/ActivityChart";
import { HealthChecks } from "./components/HealthChecks";
import { LogsPanel } from "./components/LogsPanel";
import { RunsTable } from "./components/RunsTable";
import { StatePanel } from "./components/StatePanel";
import { StatusIcon, StatusPill } from "./components/StatusIcon";

const REFRESH_MS = 60_000;

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [, setTick] = useState(0);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const s = await api.status();
      setStatus(s);
      setError(null);
      document.title = `${s.overall === "ok" ? "✓" : s.overall === "fail" ? "✕" : "!"} Parking Bot`;
    } catch (e) {
      setError((e as Error).message);
      document.title = "✕ Parking Bot";
    } finally {
      setLoading(false);
      setRefreshKey((k) => k + 1);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, REFRESH_MS);
    const tick = setInterval(() => setTick((t) => t + 1), 10_000); // keep "x s ago" fresh
    return () => {
      clearInterval(id);
      clearInterval(tick);
    };
  }, [refresh]);

  const authFailed = status && !status.authOk;

  return (
    <main className="app">
      <header className="header">
        <div>
          <h1>🅿️ Parking Bot</h1>
          <div className="sub">
            {status?.function?.name ?? "bot-parcare-craiova-api"} · eu-central-1
            {status?.identity && <> · account {status.identity.account}</>}
          </div>
        </div>
        <div className="spacer" />
        {status && <StatusPill status={status.overall} />}
        <span className="updated">{status ? `Updated ${timeAgo(status.generatedAt)}` : loading ? "Loading…" : ""}</span>
        <button className="btn" onClick={refresh} disabled={loading}>
          {loading && <span className="spinner" aria-hidden="true" />}
          Refresh
        </button>
      </header>

      {error && (
        <div className="banner" role="alert">
          <StatusIcon status="fail" />
          <div>
            <b>Can't reach the dashboard backend or AWS.</b>
            <div>{error}</div>
            <div className="updated">Is the backend running? Start it with <code>python dashboard/backend/app.py</code>.</div>
          </div>
        </div>
      )}
      {authFailed && (
        <div className="banner" role="alert">
          <StatusIcon status="fail" />
          <div>
            <b>AWS sign-in missing or expired.</b>
            <div>
              Run <code>aws login --region eu-central-1</code> in a terminal, then press Refresh.
            </div>
          </div>
        </div>
      )}

      {status && (
        <>
          <HealthChecks checks={status.checks} />
          {status.authOk && (
            <>
              <div className="cols">
                <ActionsPanel onDone={refresh} />
                <StatePanel state={status.state} />
              </div>
              <ActivityChart buckets={status.metrics} />
              <RunsTable runs={status.runs} />
              <LogsPanel refreshKey={refreshKey} />
            </>
          )}
        </>
      )}
    </main>
  );
}
