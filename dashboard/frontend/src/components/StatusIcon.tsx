import type { CheckStatus } from "../api";

const GLYPH: Record<CheckStatus, string> = { ok: "✓", warn: "!", fail: "✕", unknown: "?" };
export const STATUS_LABEL: Record<CheckStatus, string> = {
  ok: "All good",
  warn: "Needs attention",
  fail: "Failing",
  unknown: "Unknown",
};

export function StatusIcon({ status }: { status: CheckStatus }) {
  return (
    <span className={`icon ${status}`} aria-hidden="true">
      {GLYPH[status]}
    </span>
  );
}

export function StatusPill({ status }: { status: CheckStatus }) {
  return (
    <span className="pill" role="status">
      <StatusIcon status={status} />
      {STATUS_LABEL[status]}
    </span>
  );
}
