import type { Run, RunKind } from "../api";
import { clock, readableResult, timeAgo } from "../format";

const KIND: Record<RunKind, { glyph: string; cls: string; label: string }> = {
  ok: { glyph: "✓", cls: "ok", label: "Check" },
  error: { glyph: "✕", cls: "fail", label: "Failed" },
  test: { glyph: "🧪", cls: "test", label: "Test alert" },
  first: { glyph: "★", cls: "first", label: "First run" },
};

const readable = (run: Run) => (run.kind === "ok" ? readableResult(run.summary) : run.summary);

export function RunsTable({ runs }: { runs: Run[] }) {
  return (
    <section className="card">
      <h2>
        Recent runs <span className="right updated">last 6 h</span>
      </h2>
      {runs.length === 0 ? (
        <div className="empty">No runs in the last 6 hours.</div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Time</th><th>Result</th><th>Details</th><th>Duration</th></tr>
            </thead>
            <tbody>
              {runs.map((r) => {
                const k = KIND[r.kind];
                return (
                  <tr key={r.id} className={r.kind === "error" ? "error" : ""}>
                    <td className="nowrap" title={timeAgo(r.start)}>{clock(r.start)}</td>
                    <td>
                      <span className="kind"><span className={`icon ${k.cls}`} aria-hidden="true">{k.glyph}</span>{k.label}</span>
                    </td>
                    <td>{readable(r)}</td>
                    <td className="num">{r.durationMs !== null ? `${r.durationMs} ms` : "–"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
