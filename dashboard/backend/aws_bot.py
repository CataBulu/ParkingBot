"""Reads the parking bot's health from AWS: Lambda, EventBridge schedule, CloudWatch, SSM state."""
import base64
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

# `aws login` sessions need a region to refresh, and the default profile has none.
os.environ.setdefault("AWS_DEFAULT_REGION", "eu-central-1")

import boto3  # noqa: E402
from botocore.config import Config  # noqa: E402

REGION = os.environ["AWS_DEFAULT_REGION"]
FUNCTION = "bot-parcare-craiova-api"
RULE = "bot-parcare-trigger"
STATE_PARAM = "/bot-parcare/state"
LOG_GROUP = f"/aws/lambda/{FUNCTION}"
RUN_INTERVAL_MIN = 10
ERROR_THRESHOLD = 3  # same as ERROR_THRESHOLD in parking_bot.py
LOGIN_HINT = f"AWS sign-in missing or expired. Run: aws login --region {REGION}"

_clients: dict = {}
_clients_lock = threading.Lock()


def client(name: str):
    with _clients_lock:
        if name not in _clients:
            cfg = Config(read_timeout=120, retries={"max_attempts": 2})
            _clients[name] = boto3.session.Session(region_name=REGION).client(name, config=cfg)
        return _clients[name]


def reset_clients():
    """Drop cached clients so a fresh `aws login` is picked up."""
    with _clients_lock:
        _clients.clear()


def is_auth_error(e: Exception) -> bool:
    text = f"{type(e).__name__} {e}".lower()
    return any(k in text for k in ("credential", "expiredtoken", "token has expired", "unrecognizedclient",
                                   "login", "security token", "not authorized to perform sts"))


def iso(ms_or_dt) -> str | None:
    if ms_or_dt is None:
        return None
    if isinstance(ms_or_dt, (int, float)):
        ms_or_dt = datetime.fromtimestamp(ms_or_dt / 1000, tz=timezone.utc)
    return ms_or_dt.astimezone(timezone.utc).isoformat()


# ─────────────────────────────────────────
#  Individual AWS reads
# ─────────────────────────────────────────
def get_identity() -> dict:
    ident = client("sts").get_caller_identity()
    return {"account": ident["Account"], "arn": ident["Arn"]}


def get_function() -> dict:
    c = client("lambda").get_function_configuration(FunctionName=FUNCTION)
    return {  # never return Environment values: they hold the site password and Telegram token
        "name": c["FunctionName"],
        "arn": c["FunctionArn"],
        "state": c.get("State"),
        "lastUpdateStatus": c.get("LastUpdateStatus"),
        "runtime": c.get("Runtime"),
        "memoryMb": c.get("MemorySize"),
        "timeoutSec": c.get("Timeout"),
        "codeSizeKb": round(c.get("CodeSize", 0) / 1024, 1),
        "lastModified": c.get("LastModified"),
        "envVarNames": sorted((c.get("Environment") or {}).get("Variables", {}).keys()),
    }


def get_schedule() -> dict:
    ev = client("events")
    rule = ev.describe_rule(Name=RULE)
    targets = ev.list_targets_by_rule(Rule=RULE)["Targets"]
    return {
        "name": RULE,
        "state": rule.get("State"),
        "expression": rule.get("ScheduleExpression"),
        "targets": [t["Arn"] for t in targets],
    }


def get_metrics(hours: int = 24) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    return _metric_buckets(start, now, timedelta(hours=1), hours)


def get_daily_metrics(days: int = 30) -> list[dict]:
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    return _metric_buckets(start, now, timedelta(days=1), days)


def _metric_query(qid: str, metric: str, stat: str, period: int) -> dict:
    return {"Id": qid, "MetricStat": {
        "Metric": {"Namespace": "AWS/Lambda", "MetricName": metric,
                   "Dimensions": [{"Name": "FunctionName", "Value": FUNCTION}]},
        "Period": period, "Stat": stat}}


def _metric_buckets(start: datetime, end: datetime, step: timedelta, count: int) -> list[dict]:
    period = int(step.total_seconds())
    resp = client("cloudwatch").get_metric_data(
        MetricDataQueries=[_metric_query("inv", "Invocations", "Sum", period),
                           _metric_query("err", "Errors", "Sum", period),
                           _metric_query("dur", "Duration", "Average", period),
                           _metric_query("max", "Duration", "Maximum", period)],
        StartTime=start, EndTime=end, ScanBy="TimestampAscending",
    )

    def bucket_of(t: datetime) -> datetime:
        return start + step * int((t - start) / step)

    series = {r["Id"]: {bucket_of(t): v for t, v in zip(r["Timestamps"], r["Values"])}
              for r in resp["MetricDataResults"]}
    buckets = []
    for i in range(count):
        t = start + step * i
        buckets.append({
            "hour": iso(t),  # bucket start (an hour or a day)
            "invocations": int(series["inv"].get(t, 0)),
            "errors": int(series["err"].get(t, 0)),
            "avgDurationMs": round(series["dur"][t]) if t in series["dur"] else None,
            "maxDurationMs": round(series["max"][t]) if t in series["max"] else None,
        })
    return buckets


def get_month_usage(memory_mb: int = 256) -> dict:
    """Month-to-date Lambda usage against the always-free tier (1M requests, 400,000 GB-s)."""
    now = datetime.now(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    resp = client("cloudwatch").get_metric_data(
        MetricDataQueries=[_metric_query("inv", "Invocations", "Sum", 86400),
                           _metric_query("dur", "Duration", "Sum", 86400)],
        StartTime=start, EndTime=now,
    )
    totals = {r["Id"]: sum(r["Values"]) for r in resp["MetricDataResults"]}
    gb_seconds = totals.get("dur", 0) / 1000 * memory_mb / 1024
    return {
        "requests": int(totals.get("inv", 0)),
        "gbSeconds": round(gb_seconds, 1),
        "freeTierPercent": round(max(gb_seconds / 400_000, totals.get("inv", 0) / 1_000_000) * 100, 3),
    }


def get_alert_history(days: int = 7) -> dict:
    """Runs that sent real alerts (not tests) in the last `days` days."""
    events = _log_events(days * 1440, pattern='"urgent=" -"urgent=0 info=0"', max_events=500)
    runs = []
    for e in events:
        m = re.search(r"urgent=(\d+) info=(\d+)", e["message"])
        if m:
            runs.append({"ts": iso(e["timestamp"]), "urgent": int(m.group(1)), "info": int(m.group(2))})
    runs.sort(key=lambda r: r["ts"], reverse=True)
    return {
        "days": days,
        "urgentRuns": sum(1 for r in runs if r["urgent"]),
        "infoRuns": sum(1 for r in runs if r["info"] and not r["urgent"]),
        "last": runs[0] if runs else None,
    }


def get_monitoring_since() -> str | None:
    groups = client("logs").describe_log_groups(logGroupNamePrefix=LOG_GROUP)["logGroups"]
    return next((iso(g["creationTime"]) for g in groups if g["logGroupName"] == LOG_GROUP), None)


def estimate_next_run(runs: list[dict], schedule: dict | None) -> str | None:
    """EventBridge `rate()` fires at a fixed offset; the most common offset among recent runs finds it,
    even when manual runs are mixed in."""
    if not schedule or schedule.get("state") != "ENABLED":
        return None
    m = re.match(r"rate\((\d+) minutes?\)", schedule.get("expression") or "")
    if not m:
        return None
    period = int(m.group(1)) * 60
    starts = [datetime.fromisoformat(r["start"]).timestamp() for r in runs if r["kind"] != "test"]
    if not starts:
        return None
    offsets = [int(s % period) // 10 for s in starts]  # 10-second bins
    offset = max(set(offsets), key=offsets.count) * 10 + 5
    now = time.time()
    nxt = now - (now % period) + offset
    while nxt <= now:
        nxt += period
    return iso(nxt * 1000)


def get_state() -> dict | None:
    ssm = client("ssm")
    try:
        p = ssm.get_parameter(Name=STATE_PARAM)["Parameter"]
    except ssm.exceptions.ParameterNotFound:
        return None
    return {"value": json.loads(p["Value"]), "lastModified": iso(p["LastModifiedDate"]), "version": p["Version"]}


_LINE_PREFIX = re.compile(r"^\[(INFO|ERROR|WARNING|DEBUG)\]\t\S+\t\S+\t", re.M)
_REPORT = re.compile(r"Duration: ([\d.]+) ms.*?Max Memory Used: (\d+) MB(?:.*?Status: (\w+))?", re.S)


def _log_events(minutes: int, pattern: str = "", max_events: int = 2000) -> list[dict]:
    kwargs = {"logGroupName": LOG_GROUP,
              "startTime": int((time.time() - minutes * 60) * 1000)}
    if pattern:
        kwargs["filterPattern"] = pattern
    events = []
    for page in client("logs").get_paginator("filter_log_events").paginate(**kwargs):
        events.extend(page["events"])
        if len(events) >= max_events:
            break
    return events


def get_runs(hours: int = 6, limit: int = 30) -> list[dict]:
    """Group log lines into runs (START ... REPORT) and classify each one."""
    events = _log_events(hours * 60)
    by_stream: dict[str, list] = {}
    for e in events:
        by_stream.setdefault(e["logStreamName"], []).append(e)

    runs = []
    for stream_events in by_stream.values():
        stream_events.sort(key=lambda e: (e["timestamp"], e.get("ingestionTime", 0)))
        current = None
        for e in stream_events:
            msg = e["message"].rstrip()
            if msg.startswith("START RequestId:"):
                current = {"id": msg.split()[2], "start": e["timestamp"], "lines": []}
            elif current is None:
                continue
            elif msg.startswith("REPORT RequestId:"):
                m = _REPORT.search(msg)
                current["durationMs"] = round(float(m.group(1))) if m else None
                current["memoryMb"] = int(m.group(2)) if m else None
                current["reportStatus"] = m.group(3) if m else None
                runs.append(current)
                current = None
            elif not msg.startswith("END RequestId:"):
                current["lines"].append(msg)

    out = []
    for r in sorted(runs, key=lambda r: r["start"], reverse=True)[:limit]:
        text = "\n".join(r["lines"])
        clean = [_LINE_PREFIX.sub("", line) for line in r["lines"]]
        error_line = next((c for line, c in zip(r["lines"], clean)
                           if line.startswith("[ERROR]") or "Task timed out" in line), None)
        if r.get("reportStatus") in ("timeout", "error") or error_line:
            kind = "error"
            lines = text.splitlines()
            unhandled = [l[len("[ERROR] "):] for l in lines if l.startswith("[ERROR] ")]
            exc_lines = [l for l in lines if re.match(r"^[\w.]+(Error|Exception|Login)\w*: ", l)]
            if unhandled:
                summary = unhandled[0]
            elif exc_lines:
                summary = exc_lines[-1]
            else:
                summary = (error_line or f"Run ended with status {r['reportStatus']}").split("\n")[0]
        elif "TEST sent" in text:
            kind, summary = "test", next(c for c in clean if "TEST sent" in c)
        elif "First run" in text:
            kind, summary = "first", next(c for c in clean if "First run" in c).split(".")[0]
        else:
            kind = "ok"
            summary = next((c for c in clean if c.startswith("urgent=")), "Completed")
        alerts = re.search(r"urgent=(\d+) info=(\d+)", text)
        out.append({
            "id": r["id"],
            "start": iso(r["start"]),
            "kind": kind,
            "summary": summary.strip()[:400],
            "urgentAlerts": int(alerts.group(1)) if alerts else 0,
            "infoAlerts": int(alerts.group(2)) if alerts else 0,
            "durationMs": r.get("durationMs"),
            "memoryMb": r.get("memoryMb"),
        })
    return out


def get_logs(minutes: int = 60, max_lines: int = 400) -> list[dict]:
    events = _log_events(minutes, max_events=max_lines)
    events.sort(key=lambda e: (e["timestamp"], e.get("ingestionTime", 0)))
    out = []
    for e in events[-max_lines:]:
        msg = e["message"].rstrip()
        level = ("error" if msg.startswith("[ERROR]") or "Traceback" in msg or "Task timed out" in msg
                 else "meta" if msg.split(" ", 1)[0] in ("START", "END", "REPORT", "INIT_START")
                 else "info")
        out.append({"ts": iso(e["timestamp"]), "level": level, "message": _LINE_PREFIX.sub("", msg)})
    return out


def count_log_matches(pattern: str, hours: int = 24) -> int:
    return len(_log_events(hours * 60, pattern=pattern, max_events=500))


def invoke(payload: dict) -> dict:
    resp = client("lambda").invoke(FunctionName=FUNCTION, Payload=json.dumps(payload).encode(), LogType="Tail")
    raw = resp["Payload"].read()
    result = json.loads(raw) if raw else None
    log = base64.b64decode(resp.get("LogResult", "")).decode("utf-8", "replace")
    return {
        "ok": "FunctionError" not in resp,
        "functionError": resp.get("FunctionError"),
        "result": result,
        "log": _LINE_PREFIX.sub("", log),
    }


# ─────────────────────────────────────────
#  Aggregated status + health checks
# ─────────────────────────────────────────
def _check(cid, label, status, summary, **details):
    return {"id": cid, "label": label, "status": status, "summary": summary, "details": details}


def build_status() -> dict:
    now = datetime.now(timezone.utc)
    try:
        identity = get_identity()
    except Exception as e:  # noqa: BLE001 - surface any credential problem to the UI
        reset_clients()
        msg = LOGIN_HINT if is_auth_error(e) else f"{type(e).__name__}: {e}"
        return {"generatedAt": iso(now), "overall": "fail", "authOk": False, "identity": None,
                "checks": [_check("aws", "AWS access", "fail", msg)],
                "function": None, "schedule": None, "metrics": [], "daily": [], "runs": [],
                "state": None, "kpis": None}

    jobs = {"function": get_function, "schedule": get_schedule, "metrics": get_metrics,
            "daily": get_daily_metrics, "runs": get_runs, "state": get_state,
            "alerts": get_alert_history, "since": get_monitoring_since,
            "usage": get_month_usage,  # 256 MB = the function's configured memory (deploy.ps1)
            "telegramErrors": lambda: count_log_matches('"Telegram error"')}
    results, errors = {}, {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {k: pool.submit(fn) for k, fn in jobs.items()}
        for k, f in futures.items():
            try:
                results[k] = f.result()
            except Exception as e:  # noqa: BLE001
                errors[k] = f"{type(e).__name__}: {e}"

    fn, sched = results.get("function"), results.get("schedule")
    metrics, runs = results.get("metrics") or [], results.get("runs") or []
    state = results.get("state")
    checks = [_check("aws", "AWS access", "ok", f"Signed in to account {identity['account']}")]

    # Lambda function
    if "function" in errors:
        checks.append(_check("lambda", "Lambda function", "fail", errors["function"]))
    elif fn["state"] != "Active" or fn["lastUpdateStatus"] not in ("Successful", None):
        checks.append(_check("lambda", "Lambda function", "fail",
                             f"State {fn['state']}, last update {fn['lastUpdateStatus']}"))
    else:
        checks.append(_check("lambda", "Lambda function", "ok",
                             f"Active · {fn['runtime']} · {fn['memoryMb']} MB · timeout {fn['timeoutSec']} s"))

    # Schedule
    if "schedule" in errors:
        checks.append(_check("schedule", "Schedule", "fail", errors["schedule"]))
    elif fn and fn["arn"] not in sched["targets"]:
        checks.append(_check("schedule", "Schedule", "fail", "The schedule does not point at the bot function"))
    elif sched["state"] != "ENABLED":
        checks.append(_check("schedule", "Schedule", "warn", "Paused: the bot is not running automatically"))
    else:
        checks.append(_check("schedule", "Schedule", "ok", f"Enabled · {sched['expression']}"))

    # Last run: recency + result (manual test runs don't count as scheduled checks)
    real_runs = [r for r in runs if r["kind"] != "test"]
    if "runs" in errors:
        checks.append(_check("lastRun", "Last run", "fail", errors["runs"]))
    elif not real_runs:
        checks.append(_check("lastRun", "Last run", "fail", "No runs in the last 6 hours"))
    else:
        last = real_runs[0]
        age_min = (now - datetime.fromisoformat(last["start"])).total_seconds() / 60
        enabled = sched and sched["state"] == "ENABLED"
        if last["kind"] == "error":
            status, summary = "fail", f"Failed {age_min:.0f} min ago: {last['summary']}"
        elif enabled and age_min > RUN_INTERVAL_MIN * 2.5:
            status, summary = "fail", f"No run for {age_min:.0f} min (expected every {RUN_INTERVAL_MIN})"
        elif enabled and age_min > RUN_INTERVAL_MIN * 1.5:
            status, summary = "warn", f"Last run {age_min:.0f} min ago (expected every {RUN_INTERVAL_MIN})"
        else:
            status, summary = "ok", f"OK {age_min:.0f} min ago · {last['durationMs']} ms"
        checks.append(_check("lastRun", "Last run", status, summary))

    # Errors in the last 24 hours
    if metrics:
        err24 = sum(b["errors"] for b in metrics)
        inv24 = sum(b["invocations"] for b in metrics)
        last_ok = bool(real_runs) and real_runs[0]["kind"] != "error"
        status = "ok" if err24 == 0 else ("warn" if last_ok else "fail")
        checks.append(_check("errors", "Errors (24 h)", status, f"{err24} errors in {inv24} runs"))
    elif "metrics" in errors:
        checks.append(_check("errors", "Errors (24 h)", "unknown", errors["metrics"]))

    # Site login / bot's own failure counter
    if "state" in errors:
        checks.append(_check("site", "Parking site", "unknown", errors["state"]))
    elif state is None:
        checks.append(_check("site", "Parking site", "warn", "No saved state yet: the bot hasn't completed a first run"))
    else:
        fails = state["value"].get("errors", 0)
        if fails >= ERROR_THRESHOLD:
            checks.append(_check("site", "Parking site", "fail",
                                 f"{fails} failed checks in a row: Telegram warning sent"))
        elif fails:
            checks.append(_check("site", "Parking site", "warn", f"{fails} failed check(s) in a row"))
        else:
            checks.append(_check("site", "Parking site", "ok", "Login and data read OK"))

    # Telegram delivery
    if "telegramErrors" in errors:
        checks.append(_check("telegram", "Telegram", "unknown", errors["telegramErrors"]))
    elif results["telegramErrors"]:
        checks.append(_check("telegram", "Telegram", "warn",
                             f"{results['telegramErrors']} send error(s) in 24 h"))
    else:
        checks.append(_check("telegram", "Telegram", "ok", "No send errors in 24 h"))

    rank = {"ok": 0, "unknown": 1, "warn": 2, "fail": 3}
    overall = max((c["status"] for c in checks), key=lambda s: rank[s])

    daily = results.get("daily") or []
    week = daily[-7:]
    inv7, err7 = sum(b["invocations"] for b in week), sum(b["errors"] for b in week)
    inv24 = sum(b["invocations"] for b in metrics)
    dur_weighted = sum((b["avgDurationMs"] or 0) * b["invocations"] for b in metrics)
    kpis = {
        "successRate7d": round((inv7 - err7) / inv7 * 100, 1) if inv7 else None,
        "runs7d": inv7,
        "errors7d": err7,
        "runs24h": inv24,
        "avgDurationMs24h": round(dur_weighted / inv24) if inv24 else None,
        "maxDurationMs24h": max((b["maxDurationMs"] or 0 for b in metrics), default=None) or None,
        "nextRunAt": estimate_next_run(runs, sched),
        "lastRunAt": real_runs[0]["start"] if real_runs else None,
        "alerts": results.get("alerts"),
        "monitoringSince": results.get("since"),
        "usage": results.get("usage"),
    }
    return {
        "generatedAt": iso(now), "overall": overall, "authOk": True, "identity": identity,
        "checks": checks, "function": fn, "schedule": sched, "metrics": metrics,
        "daily": daily, "runs": runs, "state": state, "kpis": kpis,
    }
