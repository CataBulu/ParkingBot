import type { Check } from "../api";
import { STATUS_LABEL, StatusIcon } from "./StatusIcon";

export function HealthChecks({ checks }: { checks: Check[] }) {
  return (
    <section className="card">
      <h2>Health checks</h2>
      <div className="checks">
        {checks.map((c) => (
          <div key={c.id} className={`check ${c.status}`}>
            <StatusIcon status={c.status} />
            <div>
              <div className="label">
                {c.label} <span className="sr-only">({STATUS_LABEL[c.status]})</span>
              </div>
              <div className="summary">{c.summary}</div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
