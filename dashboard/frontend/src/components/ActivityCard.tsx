import { useEffect, useRef, useState } from "react";
import type { HourBucket } from "../api";
import { dayLabel, hourLabel, seconds } from "../format";

type Range = "24h" | "7d" | "30d";
const RANGES: { value: Range; label: string }[] = [
  { value: "24h", label: "24 hours" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
];

const PAD = { top: 12, right: 10, bottom: 24, left: 42 };
const GAP = 2; // surface gap between stacked segments and adjacent bars
const R = 4; // rounded data-end

function useWidth() {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

// Rect with only the top corners rounded (anchored to the baseline).
function topRounded(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

function niceMax(v: number) {
  if (v <= 4) return 4;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  const n = v / step;
  return (n <= 2 ? 2 : n <= 5 ? 5 : 10) * step;
}

interface Scale {
  width: number;
  height: number;
  slot: number;
  x: (i: number) => number; // column center
  y: (v: number) => number;
  maxY: number;
}

function makeScale(width: number, height: number, count: number, maxY: number): Scale {
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;
  const slot = plotW / Math.max(count, 1);
  return {
    width, height, slot, maxY,
    x: (i) => PAD.left + slot * i + slot / 2,
    y: (v) => PAD.top + plotH - (v / maxY) * plotH,
  };
}

function Axes({ s, buckets, label, tickEvery, fmtY }: {
  s: Scale; buckets: HourBucket[]; label: (iso: string) => string; tickEvery: number; fmtY: (v: number) => string;
}) {
  return (
    <>
      {[0, s.maxY / 2, s.maxY].map((t) => (
        <g key={t}>
          <line x1={PAD.left} x2={s.width - PAD.right} y1={s.y(t)} y2={s.y(t)}
            stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1} />
          <text className="axis-label" x={PAD.left - 6} y={s.y(t) + 4} textAnchor="end">{fmtY(t)}</text>
        </g>
      ))}
      {buckets.map((b, i) =>
        i % tickEvery === 0 || i === buckets.length - 1 ? (
          <text key={b.hour} className="axis-label" x={s.x(i)} y={s.height - 6} textAnchor="middle">{label(b.hour)}</text>
        ) : null,
      )}
    </>
  );
}

function Tooltip({ s, i, count, children }: { s: Scale; i: number; count: number; children: React.ReactNode }) {
  // beside the hovered column, flipping sides so it never leaves the card
  const style = i >= count / 2
    ? { top: PAD.top + 4, left: s.x(i) - s.slot / 2 - 6, transform: "translateX(-100%)" }
    : { top: PAD.top + 4, left: s.x(i) + s.slot / 2 + 6 };
  return <div className="tooltip" style={style}>{children}</div>;
}

function RunsBars({ buckets, label, tickEvery }: { buckets: HourBucket[]; label: (iso: string) => string; tickEvery: number }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const s = makeScale(width, 190, buckets.length, niceMax(Math.max(0, ...buckets.map((b) => b.invocations))));
  const barW = Math.max(3, Math.min(24, s.slot - GAP * 2));
  const total = buckets.reduce((n, b) => n + b.invocations, 0);
  const failed = buckets.reduce((n, b) => n + b.errors, 0);
  const hb = hover !== null ? buckets[hover] : null;

  return (
    <div className="chart-wrap" ref={ref}>
      <svg width={width} height={s.height} role="img" aria-label={`Bar chart: ${total} runs, ${failed} failed`}
        onMouseLeave={() => setHover(null)}>
        {hover !== null && (
          <rect x={s.x(hover) - s.slot / 2} y={PAD.top} width={s.slot} height={s.y(0) - PAD.top} fill="var(--surface-2)" />
        )}
        <Axes s={s} buckets={buckets} label={label} tickEvery={tickEvery} fmtY={(v) => String(v)} />
        {buckets.map((b, i) => {
          const x = s.x(i) - barW / 2;
          const ok = b.invocations - b.errors;
          const okTop = s.y(ok);
          const errTop = s.y(b.invocations);
          return (
            <g key={b.hour}>
              {ok > 0 && (
                <path fill="var(--series-1)" d={b.errors
                  ? `M${x},${s.y(0)}V${okTop}H${x + barW}V${s.y(0)}Z`
                  : topRounded(x, okTop, barW, s.y(0) - okTop, R)} />
              )}
              {b.errors > 0 && (
                <path fill="var(--critical)"
                  d={topRounded(x, errTop, barW, Math.max(1, okTop - errTop - (ok > 0 ? GAP : 0)), R)} />
              )}
              <rect x={s.x(i) - s.slot / 2} y={PAD.top} width={s.slot} height={s.y(0) - PAD.top}
                fill="transparent" onMouseEnter={() => setHover(i)} />
            </g>
          );
        })}
      </svg>
      {hb && hover !== null && (
        <Tooltip s={s} i={hover} count={buckets.length}>
          <div className="t">{label(hb.hour)}</div>
          <div>{hb.invocations - hb.errors} successful · {hb.errors} failed</div>
        </Tooltip>
      )}
    </div>
  );
}

function DurationLine({ buckets, label, tickEvery }: { buckets: HourBucket[]; label: (iso: string) => string; tickEvery: number }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState<number | null>(null);
  const maxMs = Math.max(0, ...buckets.map((b) => b.avgDurationMs ?? 0));
  const s = makeScale(width, 150, buckets.length, maxMs < 1000 ? 1000 : Math.ceil(maxMs / 1000) * 1000);

  // One path per run of consecutive buckets that have data (gaps stay gaps).
  const segments: string[] = [];
  let current = "";
  buckets.forEach((b, i) => {
    if (b.avgDurationMs === null) {
      if (current) segments.push(current);
      current = "";
    } else {
      current += `${current ? "L" : "M"}${s.x(i)},${s.y(b.avgDurationMs)}`;
    }
  });
  if (current) segments.push(current);
  const singles = buckets
    .map((b, i) => ({ b, i }))
    .filter(({ b, i }) => b.avgDurationMs !== null
      && (buckets[i - 1]?.avgDurationMs ?? null) === null && (buckets[i + 1]?.avgDurationMs ?? null) === null);
  const hb = hover !== null ? buckets[hover] : null;

  return (
    <div className="chart-wrap" ref={ref}>
      <svg width={width} height={s.height} role="img" aria-label="Line chart: average check duration"
        onMouseLeave={() => setHover(null)}>
        <Axes s={s} buckets={buckets} label={label} tickEvery={tickEvery} fmtY={(v) => `${v / 1000}s`} />
        {segments.map((d, k) => (
          <path key={k} d={d} fill="none" stroke="var(--series-1)" strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
        ))}
        {singles.map(({ b, i }) => (
          <circle key={b.hour} cx={s.x(i)} cy={s.y(b.avgDurationMs!)} r={3} fill="var(--series-1)" />
        ))}
        {hb && hover !== null && (
          <>
            <line x1={s.x(hover)} x2={s.x(hover)} y1={PAD.top} y2={s.y(0)} stroke="var(--axis)" strokeWidth={1} strokeDasharray="3 3" />
            {hb.avgDurationMs !== null && (
              <circle cx={s.x(hover)} cy={s.y(hb.avgDurationMs)} r={5} fill="var(--series-1)" stroke="var(--surface)" strokeWidth={2} />
            )}
          </>
        )}
        {buckets.map((b, i) => (
          <rect key={b.hour} x={s.x(i) - s.slot / 2} y={PAD.top} width={s.slot} height={s.y(0) - PAD.top}
            fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {hb && hover !== null && (
        <Tooltip s={s} i={hover} count={buckets.length}>
          <div className="t">{label(hb.hour)}</div>
          <div>{hb.avgDurationMs === null ? "no runs" : `avg ${seconds(hb.avgDurationMs)}`}</div>
          {hb.maxDurationMs !== null && <div className="muted">slowest {seconds(hb.maxDurationMs)}</div>}
        </Tooltip>
      )}
    </div>
  );
}

export function ActivityCard({ hourly, daily }: { hourly: HourBucket[]; daily: HourBucket[] }) {
  const [range, setRange] = useState<Range>("24h");
  const [showTable, setShowTable] = useState(false);
  const buckets = range === "24h" ? hourly : range === "7d" ? daily.slice(-7) : daily;
  const label = range === "24h" ? hourLabel : dayLabel;
  const tickEvery = range === "24h" ? 3 : range === "7d" ? 1 : 5;
  const unit = range === "24h" ? "hour" : "day";
  const total = buckets.reduce((n, b) => n + b.invocations, 0);
  const failed = buckets.reduce((n, b) => n + b.errors, 0);

  return (
    <section className="card">
      <div className="card-head">
        <h2>📈 Activity</h2>
        <div className="right">
          <div className="segmented" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button key={r.value} aria-pressed={range === r.value} onClick={() => setRange(r.value)}>{r.label}</button>
            ))}
          </div>
          <button className="linkish" onClick={() => setShowTable((v) => !v)}>{showTable ? "Show charts" : "Show table"}</button>
        </div>
      </div>

      {showTable ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>{unit === "hour" ? "Hour" : "Day"}</th><th>Runs</th><th>Failed</th><th>Avg time</th><th>Slowest</th></tr>
            </thead>
            <tbody>
              {[...buckets].reverse().map((b) => (
                <tr key={b.hour} className={b.errors ? "error" : ""}>
                  <td className="nowrap">{label(b.hour)}</td>
                  <td className="num">{b.invocations}</td>
                  <td className="num">{b.errors}</td>
                  <td className="num">{seconds(b.avgDurationMs)}</td>
                  <td className="num">{seconds(b.maxDurationMs)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <div className="chart-block">
            <div className="chart-title">
              Checks per {unit}
              <span className="muted">{total} runs · {failed} failed</span>
              <span className="legend" aria-hidden="true">
                <span><span className="sw" style={{ background: "var(--series-1)" }} />Successful</span>
                <span><span className="sw" style={{ background: "var(--critical)" }} />Failed</span>
              </span>
            </div>
            <RunsBars key={`bars-${range}`} buckets={buckets} label={label} tickEvery={tickEvery} />
          </div>
          <div className="chart-block">
            <div className="chart-title">
              Average check time <span className="muted">per {unit}, lower is better</span>
            </div>
            <DurationLine key={`line-${range}`} buckets={buckets} label={label} tickEvery={tickEvery} />
          </div>
        </>
      )}
    </section>
  );
}
