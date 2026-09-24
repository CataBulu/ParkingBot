import type { BotState } from "../api";
import { dateTime, timeAgo } from "../format";

export function StatePanel({ state }: { state: BotState | null }) {
  const saved = state?.value.state;
  return (
    <section className="card">
      <h2>
        What the bot sees
        {state && <span className="right updated">changed {timeAgo(state.lastModified)}</span>}
      </h2>
      {!saved ? (
        <div className="empty">No saved state yet. The first run creates it.</div>
      ) : (
        <>
          {Object.entries(saved.residences).map(([id, residence]) => {
            const lots = Object.entries(residence.lots);
            const openSession = lots.some(([, l]) => l.session_open);
            return (
              <div key={id}>
                <dl className="kv">
                  <dt>Residence</dt>
                  <dd>
                    {residence.name} <span className="updated">(ID {id})</span>
                  </dd>
                  <dt>Session</dt>
                  <dd>
                    {openSession ? (
                      <span className="tag">🟢 Open: go bid!</span>
                    ) : (
                      <span className="tag">⚪ Closed</span>
                    )}
                  </dd>
                  <dt>Registrations</dt>
                  <dd>
                    {saved.registrations.auctions} auctions · {saved.registrations.waitlist} waitlist
                  </dd>
                  <dt>Last change</dt>
                  <dd>{dateTime(state!.lastModified)}</dd>
                </dl>
                <div className="lots">
                  {lots.length === 0 ? (
                    <div className="empty">
                      No parking lots within 30 m of this residence right now. The bot will alert you when one appears or
                      a session opens.
                    </div>
                  ) : (
                    lots.map(([lotId, lot]) => (
                      <div key={lotId} className="lot">
                        <div className="name">
                          {lot.name} {lot.session_open && <span className="tag">Session open</span>}
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
