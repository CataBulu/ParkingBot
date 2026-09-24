import { useEffect, useRef, useState } from "react";
import type { HourBucket } from "../api";
import { hourLabel } from "../format";

const HEIGHT = 190;
const PAD = { top: 12, right: 8, bottom: 24, left: 30 };
const GAP = 2; // surface gap between stacked segments and adjacent bars
const R = 4; // rounded data-end

// Rect with only the top corners rounded (anchored to the baseline).
function topRounded(x: number, y: number, w: number, h: number, r: number) {
  const rr = Math.min(r, w / 2, h);
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`;
}

function niceMax(v: number) {
  if (v <= 4) return 4;
  const step = Math.pow(10, Math.floor(Math.log10(v)));
  return Math.ceil(v / step) * step;
}

export function ActivityChart({ buckets }: { buckets: HourBucket[] }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const [hover, setHover] = useState<number | null>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.max(280, e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, [showTable]);

  const maxY = niceMax(Math.max(0, ...buckets.map((b) => b.invocations)));
  const plotW = width - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const slot = plotW / Math.max(buckets.length, 1);
  const barW = Math.max(3, Math.min(22, slot - GAP * 2));
  const y = (v: number) => PAD.top + plotH - (v / maxY) * plotH;
  const ticks = [0, maxY / 2, maxY];
  const totalRuns = buckets.reduce((s, b) => s + b.invocations, 0);
  const totalErrors = buckets.reduce((s, b) => s + b.errors, 0);
  const hb = hover !== null ? buckets[hover] : null;

  return (
    <section className="card">
      <h2>
        Runs per hour, last 24 h
        <span className="right updated">
          {totalRuns} runs · {totalErrors} failed ·{" "}
          <button className="linkish" onClick={() => setShowTable((s) => !s)}>
            {showTable ? "Show chart" : "Show table"}
          </button>
        </span>
      </h2>

      {showTable ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr><th>Hour</th><th>Runs</th><th>Failed</th><th>Avg duration</th></tr>
            </thead>
            <tbody>
              {[...buckets].reverse().map((b) => (
                <tr key={b.hour} className={b.errors ? "error" : ""}>
                  <td className="nowrap">{hourLabel(b.hour)}</td>
                  <td className="num">{b.invocations}</td>
                  <td className="num">{b.errors}</td>
                  <td className="num">{b.avgDurationMs !== null ? `${b.avgDurationMs} ms` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <>
          <div className="legend" aria-hidden="true">
            <span><span className="sw" style={{ background: "var(--series-1)" }} />Successful runs</span>
            <span><span className="sw" style={{ background: "var(--critical)" }} />Failed runs</span>
          </div>
          <div className="chart-wrap" ref={wrapRef}>
            <svg
              width={width}
              height={HEIGHT}
              role="img"
              aria-label={`Bar chart: ${totalRuns} runs in the last 24 hours, ${totalErrors} failed`}
              onMouseLeave={() => setHover(null)}
            >
              {ticks.map((t) => (
                <g key={t}>
                  <line x1={PAD.left} x2={width - PAD.right} y1={y(t)} y2={y(t)}
                    stroke={t === 0 ? "var(--axis)" : "var(--grid)"} strokeWidth={1} />
                  <text className="axis-label" x={PAD.left - 6} y={y(t) + 4} textAnchor="end">{t}</text>
                </g>
              ))}
              {buckets.map((b, i) => {
                const cx = PAD.left + slot * i + slot / 2;
                const x = cx - barW / 2;
                const ok = b.invocations - b.errors;
                const okTop = y(ok);
                const errTop = y(b.invocations);
                const hasErr = b.errors > 0;
                return (
                  <g key={b.hour}>
                    {hover === i && (
                      <rect x={cx - slot / 2} y={PAD.top} width={slot} height={plotH} fill="var(--surface-2)" />
                    )}
                    {ok > 0 && (
                      <path
                        d={hasErr
                          ? `M${x},${y(0)}V${okTop}H${x + barW}V${y(0)}Z`
                          : topRounded(x, okTop, barW, y(0) - okTop, R)}
                        fill="var(--series-1)"
                      />
                    )}
                    {hasErr && (
                      <path
                        d={topRounded(x, errTop, barW, Math.max(1, okTop - errTop - (ok > 0 ? GAP : 0)), R)}
                        fill="var(--critical)"
                      />
                    )}
                    {(i % 3 === 0 || i === buckets.length - 1) && (
                      <text className="axis-label" x={cx} y={HEIGHT - 6} textAnchor="middle">
                        {hourLabel(b.hour)}
                      </text>
                    )}
                    {/* hit target: full column, larger than the mark */}
                    <rect x={cx - slot / 2} y={PAD.top} width={slot} height={plotH} fill="transparent"
                      onMouseEnter={() => setHover(i)} />
                  </g>
                );
              })}
            </svg>
            {hb && hover !== null && (
              <div
                className="tooltip"
                style={{
                  top: PAD.top + 8,
                  // beside the hovered column, flipping sides so it never leaves the card
                  ...(hover >= buckets.length / 2
                    ? { left: PAD.left + slot * hover - 6, transform: "translateX(-100%)" }
                    : { left: PAD.left + slot * (hover + 1) + 6, transform: "none" }),
                }}
              >
                <div className="t">{hourLabel(hb.hour)}</div>
                <div>{hb.invocations} runs · {hb.errors} failed</div>
                <div className="updated">{hb.avgDurationMs !== null ? `avg ${hb.avgDurationMs} ms` : "no runs"}</div>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
