import type { Kpis } from "../api";
import { dayLabel, duration, seconds, timeAgo } from "../format";

interface Tile {
  emoji: string;
  label: string;
  value: string;
  sub: string;
  help: string;
}

function tiles(k: Kpis, now: number): Tile[] {
  const alerts = k.alerts;
  const alertCount = alerts ? alerts.urgentRuns + alerts.infoRuns : 0;
  const usage = k.usage;
  return [
    {
      emoji: "✅",
      label: "Success rate",
      value: k.successRate7d === null ? "–" : `${k.successRate7d}%`,
      sub: `${k.runs7d - k.errors7d} of ${k.runs7d} checks · 7 days`,
      help: "Share of bot runs in the last 7 days that finished without an error.",
    },
    {
      emoji: "🔁",
      label: "Checks (24 h)",
      value: String(k.runs24h),
      sub: "scheduled every 10 min",
      help: "How many times the bot checked the parking site in the last 24 hours (incl. manual runs).",
    },
    {
      emoji: "⚡",
      label: "Avg check time",
      value: seconds(k.avgDurationMs24h),
      sub: `slowest ${seconds(k.maxDurationMs24h)} · 24 h`,
      help: "How long one run takes on average (login + reading the site + alerts). Test alerts take longer.",
    },
    {
      emoji: "🔔",
      label: "Alerts sent",
      value: String(alertCount),
      sub: alerts?.last ? `last ${timeAgo(alerts.last.ts, now)} · 7 days` : "none in the last 7 days",
      help: "Runs that sent you a real Telegram alert in the last 7 days (test alerts not counted).",
    },
    {
      emoji: "🛰️",
      label: "Monitoring for",
      value: k.monitoringSince ? duration(k.monitoringSince, now) : "–",
      sub: k.monitoringSince ? `since ${dayLabel(k.monitoringSince)}` : "",
      help: "How long this version of the bot has been running.",
    },
    {
      emoji: "💶",
      label: "Cost this month",
      value: usage && usage.freeTierPercent < 100 ? "$0.00" : "–",
      sub: usage ? `${usage.freeTierPercent}% of the AWS free tier` : "",
      help: usage
        ? `${usage.requests} runs and ${usage.gbSeconds} GB-seconds this month. Lambda's always-free tier covers 1M runs and 400,000 GB-seconds.`
        : "",
    },
  ];
}

export function KpiTiles({ kpis, now }: { kpis: Kpis; now: number }) {
  return (
    <section className="kpis" aria-label="Key metrics">
      {tiles(kpis, now).map((t) => (
        <div key={t.label} className="kpi" title={t.help}>
          <div className="k-label">
            <span className="k-emoji" aria-hidden="true">{t.emoji}</span>
            {t.label}
          </div>
          <div className="k-value">{t.value}</div>
          <div className="k-sub">{t.sub}</div>
        </div>
      ))}
    </section>
  );
}
