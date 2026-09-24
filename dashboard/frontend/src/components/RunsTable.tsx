import { useState } from "react";
import type { Run, RunKind } from "../api";
import { clock, readableResult, seconds, timeAgo } from "../format";
import type { Redact } from "../privacy";

const KIND: Record<RunKind, { glyph: string; cls: string; label: string }> = {
  ok: { glyph: "✓", cls: "ok", label: "Check" },
  error: { glyph: "✕", cls: "fail", label: "Failed" },
  test: { glyph: "🧪", cls: "test", label: "Test alert" },
  first: { glyph: "★", cls: "first", label: "First run" },
};

const COLLAPSED_ROWS = 8;
const readable = (run: Run) => (run.kind === "ok" ? readableResult(run.summary) : run.summary);

export function RunsTable({ runs, now, redact }: { runs: Run[]; now: number; redact: Redact }) {
  const [showAll, setShowAll] = useState(false);
  const shown = showAll ? runs : runs.slice(0, COLLAPSED_ROWS);
  return (
    <section className="card">
      <div className="card-head">
        <h2>🧾 Recent runs</h2>
        <span className="right muted">last 6 hours</span>
      </div>
      {runs.length === 0 ? (
        <div className="empty">😴 No runs in the last 6 hours.</div>
      ) : (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr><th>Time</th><th>Result</th><th>Details</th><th>Duration</th></tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const k = KIND[r.kind];
                  return (
                    <tr key={r.id} className={r.kind === "error" ? "error" : ""}>
                      <td className="nowrap" title={clock(r.start)}>{timeAgo(r.start, now)}</td>
                      <td>
                        <span className="kind"><span className={`icon ${k.cls}`} aria-hidden="true">{k.glyph}</span>{k.label}</span>
                      </td>
                      <td>{redact(readable(r))}</td>
                      <td className="num">{seconds(r.durationMs)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {runs.length > COLLAPSED_ROWS && (
            <div className="table-foot">
              <button className="btn small" onClick={() => setShowAll((v) => !v)}>
                {showAll ? "Show fewer" : `Show all ${runs.length} runs`}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
