import { useState } from "react";
import { api, type InvokeResult } from "../api";
import { readableResult } from "../format";
import type { Notify } from "./Toasts";

type Action = "test" | "check";

const LOG_INGEST_DELAY_MS = 4000; // CloudWatch needs a few seconds before the new run shows up

export function ActionsPanel({ onDone, notify }: { onDone: () => void; notify: Notify }) {
  const [busy, setBusy] = useState<Action | null>(null);
  const [repetitions, setRepetitions] = useState(1);

  function report(action: Action, r: InvokeResult) {
    if (!r.ok) {
      const msg = r.result?.errorMessage ?? r.error ?? r.functionError ?? "Unknown error";
      notify({ ok: false, title: "The bot failed", text: msg, log: r.log });
    } else if (action === "test") {
      notify({ ok: true, title: "Test alert sent 📨", text: "Check your Telegram.", log: r.log });
    } else {
      notify({ ok: true, title: "Check complete", text: readableResult(r.result?.body ?? "Done"), log: r.log });
    }
  }

  async function run(action: Action) {
    setBusy(action);
    try {
      report(action, action === "test" ? await api.testAlert(repetitions) : await api.runCheck());
    } catch (e) {
      notify({ ok: false, title: "Couldn't run the bot", text: (e as Error).message });
    } finally {
      setBusy(null);
      setTimeout(onDone, LOG_INGEST_DELAY_MS);
    }
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>🎛️ Actions</h2>
      </div>
      <div className="actions">
        <div className="action">
          <div className="a-title">📨 Test the Telegram alerts</div>
          <p>
            Sends a <b>🧪 TEST</b> alert to your phone. The bot really logs in and reads the site, then pretends a
            session opened with 2 free spots. Nothing is saved.
          </p>
          <div className="row">
            <button className="btn primary" disabled={busy !== null} onClick={() => run("test")}>
              {busy === "test" && <span className="spinner" aria-hidden="true" />}
              {busy === "test" ? "Sending…" : "Send test alert"}
            </button>
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
          </div>
        </div>

        <div className="action">
          <div className="a-title">🔍 Check the site now</div>
          <p>Runs a normal check right away instead of waiting for the schedule. You only get alerts if something changed.</p>
          <div className="row">
            <button className="btn" disabled={busy !== null} onClick={() => run("check")}>
              {busy === "check" && <span className="spinner" aria-hidden="true" />}
              {busy === "check" ? "Checking…" : "Run check now"}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
