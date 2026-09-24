import { useCallback, useEffect, useState } from "react";
import { api, type LogLine } from "../api";
import { clock } from "../format";
import type { Redact } from "../privacy";

export function LogsPanel({ refreshKey, redact }: { refreshKey: number; redact: Redact }) {
  const [open, setOpen] = useState(false);
  const [minutes, setMinutes] = useState(60);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [errorsOnly, setErrorsOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setLines((await api.logs(minutes)).lines);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [minutes]);

  useEffect(() => {
    if (open) load(); // only fetch logs while the section is open
  }, [open, load, refreshKey]);

  const shown = errorsOnly ? lines.filter((l) => l.level === "error") : lines;
  const errorCount = lines.filter((l) => l.level === "error").length;

  return (
    <details className="card" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <span className="chev" aria-hidden="true">▶</span>
        🛠️ Technical logs
        <span className="muted" style={{ fontWeight: 400 }}>raw Lambda output, for troubleshooting</span>
      </summary>
      {open && (
        <>
          <div className="log-tools">
            <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Time range">
              <option value={30}>Last 30 min</option>
              <option value={60}>Last hour</option>
              <option value={360}>Last 6 hours</option>
              <option value={1440}>Last 24 hours</option>
            </select>
            <label className="muted">
              <input type="checkbox" checked={errorsOnly} onChange={(e) => setErrorsOnly(e.target.checked)} /> errors only
              {lines.length > 0 && ` (${errorCount})`}
            </label>
            <button className="btn small" onClick={load} disabled={loading}>
              {loading ? <span className="spinner" aria-hidden="true" /> : "↻"} Reload
            </button>
          </div>
          {error ? (
            <div className="empty">✕ {error}</div>
          ) : shown.length === 0 ? (
            <div className="empty">{loading ? "Loading…" : errorsOnly ? "No errors in this period. 👍" : "No log lines in this period."}</div>
          ) : (
            <div className="logs">
              {[...shown].reverse().map((l, i) => (
                <div key={i} className={`log-line ${l.level}`}>
                  <span className="ts">{clock(l.ts)}</span>
                  <span>{redact(l.message)}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </details>
  );
}
