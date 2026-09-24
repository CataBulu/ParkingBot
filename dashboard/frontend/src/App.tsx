import { useCallback, useEffect, useState } from "react";
import { api, type Status } from "./api";
import { timeAgo } from "./format";
import { usePrivacy } from "./privacy";
import { ActionsPanel } from "./components/ActionsPanel";
import { ActivityCard } from "./components/ActivityCard";
import { HealthChecks } from "./components/HealthChecks";
import { Hero } from "./components/Hero";
import { KpiTiles } from "./components/KpiTiles";
import { LogsPanel } from "./components/LogsPanel";
import { RunsTable } from "./components/RunsTable";
import { StatePanel } from "./components/StatePanel";
import { StatusIcon } from "./components/StatusIcon";
import { ThemeSwitch, useTheme } from "./components/ThemeSwitch";
import { Toasts, useToasts } from "./components/Toasts";

const REFRESH_MS = 60_000;

export default function App() {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const [now, setNow] = useState(Date.now());
  const [theme, setTheme] = useTheme();
  const { toasts, notify, dismiss } = useToasts();
  const { privacyOn, setPrivacyOn, redact } = usePrivacy(status);

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
    const tick = setInterval(() => setNow(Date.now()), 1000); // live countdown / "x ago"
    return () => {
      clearInterval(id);
      clearInterval(tick);
    };
  }, [refresh]);

  const authFailed = status && !status.authOk;

  return (
    <>
      <main className="app">
        <header className="header">
          <div className="brand">
            <div className="logo" aria-hidden="true">P</div>
            <div>
              <h1>Parking Bot</h1>
              <div className="sub">
                Craiova residential parking watcher
                {status?.identity && <> · AWS {redact(status.identity.account)}</>}
              </div>
            </div>
          </div>
          <div className="spacer" />
          <ThemeSwitch theme={theme} onChange={setTheme} />
          <button className="btn small" onClick={() => setPrivacyOn(!privacyOn)} aria-pressed={privacyOn}
            title="Hide your address, residence ID and AWS account number (safe for screenshots)">
            {privacyOn ? "🔒 Private" : "🔓 Details shown"}
          </button>
          <button className="btn small" onClick={refresh} disabled={loading} title="Reload everything from AWS">
            {loading ? <span className="spinner" aria-hidden="true" /> : "↻"}
            {status ? ` ${timeAgo(status.generatedAt, now)}` : " Refresh"}
          </button>
        </header>

        {error && (
          <div className="banner" role="alert">
            <StatusIcon status="fail" />
            <div>
              <b>Can't reach the dashboard backend or AWS.</b>
              <div>{error}</div>
              <div className="muted">Is the backend running? Start it with <code>dashboard\start.ps1</code>.</div>
            </div>
          </div>
        )}
        {authFailed && (
          <div className="banner" role="alert">
            <StatusIcon status="fail" />
            <div>
              <b>Your AWS sign-in has expired.</b>
              <div>
                Run <code>aws login --region eu-central-1</code> in a terminal, then press ↻.
              </div>
            </div>
          </div>
        )}
        {!status && !error && <div className="card hero"><span className="spinner" /> Loading the bot's status from AWS…</div>}

        {status?.authOk && (
          <>
            <Hero status={status} now={now} redact={redact} />
            {status.kpis && <KpiTiles kpis={status.kpis} now={now} />}
            <HealthChecks checks={status.checks} redact={redact} />
            <div className="cols">
              <ActionsPanel onDone={refresh} notify={notify} />
              <StatePanel state={status.state} now={now} redact={redact} />
            </div>
            <ActivityCard hourly={status.metrics} daily={status.daily} />
            <RunsTable runs={status.runs} now={now} redact={redact} />
            <LogsPanel refreshKey={refreshKey} redact={redact} />
          </>
        )}
        {authFailed && <HealthChecks checks={status.checks} redact={redact} />}
      </main>
      <Toasts toasts={toasts} dismiss={dismiss} />
    </>
  );
}
