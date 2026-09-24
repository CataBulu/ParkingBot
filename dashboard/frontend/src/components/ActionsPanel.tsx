import { useState } from "react";
import { api, type InvokeResult } from "../api";
import { readableResult } from "../format";

const LOG_INGEST_DELAY_MS = 4000; // CloudWatch needs a few seconds before the new run shows up

type Action = "test" | "check";

interface Outcome {
  action: Action;
  ok: boolean;
  text: string;
  log?: string;
}

function describe(action: Action, r: InvokeResult): Outcome {
  if (!r.ok) {
    const msg = r.result?.errorMessage ?? r.error ?? r.functionError ?? "Unknown error";
    return { action, ok: false, text: `The bot failed: ${msg}`, log: r.log };
  }
  return { action, ok: true, text: readableResult(r.result?.body ?? "Done"), log: r.log };
}

export function ActionsPanel({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState<Action | null>(null);
  const [repetitions, setRepetitions] = useState(1);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  async function run(action: Action) {
    setBusy(action);
    setOutcome(null);
    try {
      const r = action === "test" ? await api.testAlert(repetitions) : await api.runCheck();
      setOutcome(describe(action, r));
    } catch (e) {
      setOutcome({ action, ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
      setTimeout(onDone, LOG_INGEST_DELAY_MS);
    }
  }

  return (
    <section className="card">
      <h2>Actions</h2>
      <div className="actions">
        <div className="action">
          <p>
            Sends a <b>🧪 TEST</b> alert to your Telegram. The bot logs in and reads the real site data, then
            simulates an open session with 2 free spots. The saved state is not changed.
          </p>
          <div className="row">
            <button className="btn primary" disabled={busy !== null} onClick={() => run("test")}>
              {busy === "test" && <span className="spinner" aria-hidden="true" />}
              {busy === "test" ? "Sending…" : "Send test alert"}
            </button>
            <label>
              <select
                value={repetitions}
                disabled={busy !== null}
                onChange={(e) => setRepetitions(Number(e.target.value))}
                aria-label="Number of test messages"
              >
                <option value={1}>1 message</option>
                <option value={3}>3 messages</option>
                <option value={10}>10 messages (like a real alert)</option>
              </select>
            </label>
          </div>
        </div>

        <div className="action">
          <p>
            Runs a normal check now, the same as the 10-minute schedule. If something changed on the site, you get the
            real alerts.
          </p>
          <div className="row">
            <button className="btn" disabled={busy !== null} onClick={() => run("check")}>
              {busy === "check" && <span className="spinner" aria-hidden="true" />}
              {busy === "check" ? "Checking…" : "Run check now"}
            </button>
          </div>
        </div>

        {outcome && (
          <div className={`result ${outcome.ok ? "" : "error"}`} role="status">
            <b>{outcome.ok ? "✓ " : "✕ "}</b>
            {outcome.action === "test" && outcome.ok ? "Test alert sent. Check Telegram. " : ""}
            {outcome.text}
            {outcome.log && (
              <details>
                <summary>Lambda log</summary>
                <pre>{outcome.log.trim()}</pre>
              </details>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
