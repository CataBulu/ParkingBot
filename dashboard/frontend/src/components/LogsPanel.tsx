import { useCallback, useEffect, useState } from "react";
import { api, type LogLine } from "../api";
import { clock } from "../format";

export function LogsPanel({ refreshKey }: { refreshKey: number }) {
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
    load();
  }, [load, refreshKey]);

  const shown = errorsOnly ? lines.filter((l) => l.level === "error") : lines;

  return (
    <section className="card">
      <h2>
        Lambda logs
        <span className="right" style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <label className="updated">
            <input type="checkbox" checked={errorsOnly} onChange={(e) => setErrorsOnly(e.target.checked)} /> errors only
          </label>
          <select value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Time range">
            <option value={30}>30 min</option>
            <option value={60}>1 hour</option>
            <option value={360}>6 hours</option>
            <option value={1440}>24 hours</option>
          </select>
          <button className="btn" onClick={load} disabled={loading}>
            {loading ? <span className="spinner" aria-hidden="true" /> : "↻"}
          </button>
        </span>
      </h2>
      {error ? (
        <div className="result error">{error}</div>
      ) : shown.length === 0 ? (
        <div className="empty">{errorsOnly ? "No errors in this period. 👍" : "No log lines in this period."}</div>
      ) : (
        <div className="logs">
          {[...shown].reverse().map((l, i) => (
            <div key={i} className={`log-line ${l.level}`}>
              <span className="ts">{clock(l.ts)}</span>
              <span>{l.message}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
