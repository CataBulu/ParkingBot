import type { Check } from "../api";
import { STATUS_LABEL, StatusIcon } from "./StatusIcon";
import type { Redact } from "../privacy";

const ABOUT: Record<string, { emoji: string; help: string }> = {
  aws: { emoji: "🔑", help: "The dashboard can read your AWS account (your `aws login` session)." },
  lambda: { emoji: "⚙️", help: "The bot's Lambda function exists, is active and its last update succeeded." },
  schedule: { emoji: "⏰", help: "The 10-minute EventBridge schedule is on and points at the bot." },
  lastRun: { emoji: "🕒", help: "The latest scheduled run finished OK and happened on time." },
  errors: { emoji: "🐞", help: "Failed runs in the last 24 hours, from CloudWatch metrics." },
  site: { emoji: "🅿️", help: "The bot can log in to the parking site and read the data." },
  telegram: { emoji: "💬", help: "Telegram accepted every message in the last 24 hours." },
};

export function HealthChecks({ checks, redact }: { checks: Check[]; redact: Redact }) {
  const okCount = checks.filter((c) => c.status === "ok").length;
  return (
    <section className="card">
      <div className="card-head">
        <h2>🩺 Health checks</h2>
        <span className="right muted">{okCount} of {checks.length} OK</span>
        <span className="hint">Everything the bot needs to alert you. Hover a check to see what it means.</span>
      </div>
      <div className="checks">
        {checks.map((c) => {
          const about = ABOUT[c.id] ?? { emoji: "•", help: "" };
          return (
            <div key={c.id} className={`check ${c.status}`} title={about.help}>
              <span className="c-emoji" aria-hidden="true">{about.emoji}</span>
              <div>
                <div className="label">
                  {c.label} <StatusIcon status={c.status} />
                  <span className="sr-only">({STATUS_LABEL[c.status]})</span>
                </div>
                <div className="summary">{redact(c.summary)}</div>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
