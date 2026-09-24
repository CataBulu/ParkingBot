import { useEffect, useMemo, useState } from "react";
import type { Status } from "./api";

const KEY = "parking-bot-privacy";

export type Redact = (text: string) => string;

// Privacy mode (on by default) hides the address, residence ID and AWS account number,
// so the dashboard is safe to screenshot.
export function usePrivacy(status: Status | null) {
  const [on, setOn] = useState<boolean>(() => {
    try {
      return localStorage.getItem(KEY) !== "off";
    } catch {
      return true;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(KEY, on ? "on" : "off");
    } catch {
      /* ignore */
    }
  }, [on]);

  const redact: Redact = useMemo(() => {
    if (!on || !status) return (t) => t;
    const replacements: [string, string][] = [];
    const account = status.identity?.account;
    if (account) replacements.push([account, `••••${account.slice(-2)}`]);
    for (const [id, r] of Object.entries(status.state?.value.state?.residences ?? {})) {
      if (r.name) replacements.push([r.name, "your residence"]);
      replacements.push([id, "•••"]);
    }
    const escaped = replacements
      .sort((a, b) => b[0].length - a[0].length)
      .map(([from]) => from.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    if (escaped.length === 0) return (t) => t;
    const re = new RegExp(`(?<![\\w])(?:${escaped.join("|")})(?![\\w])`, "gi");
    const lookup = new Map(replacements.map(([from, to]) => [from.toLowerCase(), to]));
    return (t) => t.replace(re, (m) => lookup.get(m.toLowerCase()) ?? "•••");
  }, [on, status]);

  return { privacyOn: on, setPrivacyOn: setOn, redact };
}
