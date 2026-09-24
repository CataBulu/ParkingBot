export type CheckStatus = "ok" | "warn" | "fail" | "unknown";

export interface Check {
  id: string;
  label: string;
  status: CheckStatus;
  summary: string;
}

export interface LambdaInfo {
  name: string;
  arn: string;
  state: string;
  lastUpdateStatus: string;
  runtime: string;
  memoryMb: number;
  timeoutSec: number;
  codeSizeKb: number;
  lastModified: string;
  envVarNames: string[];
}

export interface Schedule {
  name: string;
  state: string;
  expression: string;
  targets: string[];
}

export interface HourBucket {
  hour: string; // bucket start: an hour (metrics) or a day (daily)
  invocations: number;
  errors: number;
  avgDurationMs: number | null;
  maxDurationMs: number | null;
}

export interface Kpis {
  successRate7d: number | null;
  runs7d: number;
  errors7d: number;
  runs24h: number;
  avgDurationMs24h: number | null;
  maxDurationMs24h: number | null;
  nextRunAt: string | null;
  lastRunAt: string | null;
  alerts: { days: number; urgentRuns: number; infoRuns: number; last: { ts: string; urgent: number; info: number } | null } | null;
  monitoringSince: string | null;
  usage: { requests: number; gbSeconds: number; freeTierPercent: number } | null;
}

export type RunKind = "ok" | "error" | "test" | "first";

export interface Run {
  id: string;
  start: string;
  kind: RunKind;
  summary: string;
  urgentAlerts: number;
  infoAlerts: number;
  durationMs: number | null;
  memoryMb: number | null;
}

export interface ParkingLot {
  name: string;
  session_open: boolean;
  waitlist_open: boolean;
  total: number;
  free: string[];
}

export interface BotState {
  value: {
    state?: {
      residences: Record<string, { name: string; lots: Record<string, ParkingLot> }>;
      registrations: { auctions: number; waitlist: number; fingerprint: string };
    };
    errors?: number;
  };
  lastModified: string;
  version: number;
}

export interface Status {
  generatedAt: string;
  overall: CheckStatus;
  authOk: boolean;
  identity: { account: string; arn: string } | null;
  checks: Check[];
  function: LambdaInfo | null;
  schedule: Schedule | null;
  metrics: HourBucket[];
  daily: HourBucket[];
  runs: Run[];
  state: BotState | null;
  kpis: Kpis | null;
}

export interface LogLine {
  ts: string;
  level: "info" | "error" | "meta";
  message: string;
}

export interface InvokeResult {
  ok: boolean;
  functionError?: string | null;
  result?: { statusCode?: number; body?: string; errorMessage?: string; errorType?: string } | null;
  log?: string;
  error?: string;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const data = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data as T;
}

const postJson = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  status: () => request<Status>("/api/status"),
  logs: (minutes: number) => request<{ minutes: number; lines: LogLine[] }>(`/api/logs?minutes=${minutes}`),
  testAlert: (repetitions: number) => request<InvokeResult>("/api/actions/test-alert", postJson({ repetitions })),
  runCheck: () => request<InvokeResult>("/api/actions/run-check", postJson({})),
};
