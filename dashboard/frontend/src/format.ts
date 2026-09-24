export function timeAgo(iso: string, now = Date.now()): string {
  const sec = Math.round((now - new Date(iso).getTime()) / 1000);
  if (sec < 60) return `${Math.max(sec, 0)} s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}

// Bot result "urgent=0 info=0 | 🏠 ... | 📋 ..." -> "No changes · 🏠 ... · 📋 ..."
export function readableResult(body: string): string {
  const m = body.match(/^urgent=(\d+) info=(\d+)/);
  if (!m) return body;
  const [urgent, info] = [Number(m[1]), Number(m[2])];
  const alerts = urgent || info ? `🚨 ${urgent} urgent, ℹ️ ${info} info alert(s) sent` : "No changes";
  return [alerts, ...body.split(" | ").slice(1)].join(" · ");
}

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export const hourLabel = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

export const dayLabel = (iso: string) => new Date(iso).toLocaleDateString([], { day: "numeric", month: "short" });

export function seconds(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "–";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function countdown(iso: string, now = Date.now()): string {
  const sec = Math.round((new Date(iso).getTime() - now) / 1000);
  if (sec <= 0) return "any moment";
  return `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
}

export function duration(fromIso: string, now = Date.now()): string {
  const min = Math.max(0, Math.round((now - new Date(fromIso).getTime()) / 60000));
  if (min < 60) return `${min} min`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${h} h ${min % 60} min`;
  return `${Math.floor(h / 24)} days`;
}

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
