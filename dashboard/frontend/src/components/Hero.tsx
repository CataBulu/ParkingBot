import type { Status } from "../api";
import { countdown, timeAgo } from "../format";
import { StatusIcon } from "./StatusIcon";
import type { Redact } from "../privacy";

const HEADLINE = {
  ok: ["All systems go", "The bot is watching the parking site for you and will ping you on Telegram."],
  warn: ["Something needs a look", "The bot is still running, but one of the checks below isn't quite right."],
  fail: ["The bot needs your attention", "It may not be able to alert you right now. See what's failing below."],
  unknown: ["Checking…", "Some information couldn't be read from AWS."],
} as const;

export function Hero({ status, now, redact }: { status: Status; now: number; redact: Redact }) {
  const [title, text] = HEADLINE[status.overall];
  const issues = status.checks.filter((c) => c.status === "warn" || c.status === "fail");
  const k = status.kpis;
  const lots = Object.values(status.state?.value.state?.residences ?? {}).flatMap((r) => Object.values(r.lots));
  const sessionOpen = lots.some((l) => l.session_open);
  const free = lots.reduce((n, l) => n + l.free.length, 0);
  const paused = status.schedule && status.schedule.state !== "ENABLED";

  return (
    <section className={`card hero ${status.overall}`} aria-live="polite">
      <span className={`icon big ${status.overall}`} aria-hidden="true">
        {{ ok: "✓", warn: "!", fail: "✕", unknown: "?" }[status.overall]}
      </span>
      <div>
        <h2>{title}</h2>
        <p>{text}</p>
        {issues.length > 0 && (
          <ul className="issues">
            {issues.map((c) => (
              <li key={c.id}>
                <b>{c.label}:</b> {redact(c.summary)}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="chips">
        {k?.lastRunAt && (
          <span className="chip">🕒 Last check <b>{timeAgo(k.lastRunAt, now)}</b></span>
        )}
        {paused ? (
          <span className="chip"><StatusIcon status="warn" /> Schedule <b>paused</b></span>
        ) : (
          k?.nextRunAt && <span className="chip">⏳ Next check in <b>{countdown(k.nextRunAt, now)}</b></span>
        )}
        <span className="chip">
          🅿️ Session <b>{sessionOpen ? "OPEN, go bid!" : "closed"}</b>
        </span>
        <span className="chip">
          🚗 <b>{free}</b> free spot{free === 1 ? "" : "s"} nearby
        </span>
      </div>
    </section>
  );
}
