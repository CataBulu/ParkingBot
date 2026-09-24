import type { BotState } from "../api";
import { dateTime, timeAgo } from "../format";
import type { Redact } from "../privacy";

export function StatePanel({ state, now, redact }: { state: BotState | null; now: number; redact: Redact }) {
  const saved = state?.value.state;
  const residences = Object.entries(saved?.residences ?? {});
  const lots = residences.flatMap(([, r]) => Object.values(r.lots));
  const free = lots.reduce((n, l) => n + l.free.length, 0);
  const sessionOpen = lots.some((l) => l.session_open);

  return (
    <section className="card">
      <div className="card-head">
        <h2>🅿️ What the bot sees</h2>
        {state && <span className="right muted">updated {timeAgo(state.lastModified, now)}</span>}
      </div>
      {!saved ? (
        <div className="empty">⏳ No saved state yet. The first run creates it.</div>
      ) : (
        <>
          <div className="mini-stats">
            <div className="mini">
              <div className="v">{sessionOpen ? "🟢" : "⚪"}</div>
              <div className="l">Session {sessionOpen ? "open" : "closed"}</div>
            </div>
            <div className="mini">
              <div className="v">{lots.length}</div>
              <div className="l">lots within 30 m</div>
            </div>
            <div className="mini">
              <div className="v">{free}</div>
              <div className="l">free spots</div>
            </div>
          </div>
          {residences.map(([id, residence]) => {
            const entries = Object.entries(residence.lots);
            return (
              <div key={id}>
                <dl className="kv">
                  <dt>Residence</dt>
                  <dd>{redact(residence.name)}</dd>
                  <dt>Registrations</dt>
                  <dd>
                    {saved.registrations.auctions} auctions · {saved.registrations.waitlist} waitlist
                  </dd>
                  <dt>Last change</dt>
                  <dd>{dateTime(state!.lastModified)}</dd>
                </dl>
                <div className="lots">
                  {entries.length === 0 ? (
                    <div className="empty">
                      <span aria-hidden="true">🔭</span>
                      <span>
                        No parking lots near this residence right now, and no session is open. That's normal between
                        sessions. The bot will ping you as soon as that changes.
                      </span>
                    </div>
                  ) : (
                    entries.map(([lotId, lot]) => (
                      <div key={lotId} className="lot">
                        <div className="name">
                          {lot.name} {lot.session_open && <span className="tag">🟢 Session open</span>}
                        </div>
                        <div className="meta">
                          {lot.free.length} of {lot.total} spots free
                          {lot.free.length > 0 && <> · spots {lot.free.join(", ")}</>}
                          {lot.waitlist_open && <> · waitlist open</>}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </>
      )}
    </section>
  );
}
