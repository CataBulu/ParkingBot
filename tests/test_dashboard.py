"""Dashboard backend: CloudWatch log parsing, health logic and the API's request guards."""
import time
from datetime import datetime, timezone

import pytest
from botocore.exceptions import NoCredentialsError
from starlette.testclient import TestClient

import app as dashboard_app
import aws_bot

NOW_MS = int(time.time() * 1000)


def event(stream, seconds_ago, message):
    return {"logStreamName": stream, "timestamp": NOW_MS - seconds_ago * 1000, "message": message + "\n"}


# One failed login, one timeout and one successful run, formatted like Lambda (python3.12) logs them.
FAKE_LOGS = [
    event("s1", 600, "START RequestId: aaa Version: $LATEST"),
    event("s1", 599, "[ERROR]\t2026-01-01T00:00:00Z\taaa\tCheck failed (1 in a row)\nTraceback (most recent call last):\n"
                     "urllib.error.HTTPError: HTTP Error 401: UNAUTHORIZED\n\nTraceback (most recent call last):\n"
                     "parking_bot.LoginError: Login failed: wrong password"),
    event("s1", 598, "[ERROR] LoginError: Login failed: wrong password\nTraceback (most recent call last):\n"
                     "  File \"/var/task/parking_bot.py\", line 250, in handler"),
    event("s1", 598, "END RequestId: aaa"),
    event("s1", 598, "REPORT RequestId: aaa\tDuration: 912.1 ms\tBilled Duration: 913 ms\tMemory Size: 256 MB\tMax Memory Used: 97 MB"),
    event("s2", 300, "START RequestId: bbb Version: $LATEST"),
    event("s2", 210, "2026-01-01T00:05:00Z bbb Task timed out after 90.09 seconds"),
    event("s2", 210, "REPORT RequestId: bbb\tDuration: 90090.0 ms\tBilled Duration: 90000 ms\tMemory Size: 256 MB\tMax Memory Used: 99 MB\tStatus: timeout"),
    event("s1", 60, "START RequestId: ccc Version: $LATEST"),
    event("s1", 59, "[INFO]\t2026-01-01T00:09:00Z\tccc\turgent=2 info=1 | 🏠 Your residence: 1 parking lots within 30 m"),
    event("s1", 59, "REPORT RequestId: ccc\tDuration: 30100.5 ms\tBilled Duration: 30101 ms\tMemory Size: 256 MB\tMax Memory Used: 98 MB"),
]


@pytest.fixture
def fake_logs(monkeypatch):
    monkeypatch.setattr(aws_bot, "_log_events", lambda minutes, pattern="", max_events=2000: list(FAKE_LOGS))


def test_runs_are_grouped_and_classified(fake_logs):
    runs = aws_bot.get_runs()
    assert [r["id"] for r in runs] == ["ccc", "bbb", "aaa"]  # newest first
    ok, timeout, login = runs
    assert ok["kind"] == "ok" and (ok["urgentAlerts"], ok["infoAlerts"]) == (2, 1) and ok["durationMs"] == 30100
    assert timeout["kind"] == "error" and "Task timed out" in timeout["summary"]
    assert login["kind"] == "error" and login["summary"] == "LoginError: Login failed: wrong password"


def test_log_lines_get_levels(fake_logs):
    levels = [line["level"] for line in aws_bot.get_logs(60)]
    assert levels.count("error") == 3
    assert "meta" in levels and "info" in levels


def test_expired_sign_in_gives_one_clear_failing_check(monkeypatch):
    def no_credentials():
        raise NoCredentialsError()

    monkeypatch.setattr(aws_bot, "get_identity", no_credentials)
    status = aws_bot.build_status()
    assert status["overall"] == "fail" and status["authOk"] is False
    assert len(status["checks"]) == 1 and "aws login" in status["checks"][0]["summary"]


def test_next_run_follows_the_schedule_offset_not_manual_runs():
    now = time.time()
    base = now - (now % 600) + 204 - 3600  # scheduled runs at :x3:24 for the last hour
    scheduled = [base + 600 * k for k in range(6)]
    manual = [base + 600 * 3 + 311]  # e.g. a "Run check now" at another offset
    runs = [{"kind": "ok", "start": datetime.fromtimestamp(t, tz=timezone.utc).isoformat()} for t in scheduled + manual]
    next_run = datetime.fromisoformat(aws_bot.estimate_next_run(runs, {"state": "ENABLED", "expression": "rate(10 minutes)"}))
    assert abs(next_run.timestamp() % 600 - 205) < 1  # 10-second bin of the :x3:24 offset
    assert 0 < next_run.timestamp() - now <= 600


def test_no_next_run_when_schedule_is_paused():
    runs = [{"kind": "ok", "start": datetime.now(timezone.utc).isoformat()}]
    assert aws_bot.estimate_next_run(runs, {"state": "DISABLED", "expression": "rate(10 minutes)"}) is None


# ── API request guards (no AWS call is made: requests are rejected first) ──

@pytest.fixture
def client():
    return TestClient(dashboard_app.app, base_url="http://127.0.0.1:8765")


def test_rejects_cross_site_origin(client):
    r = client.post("/api/actions/test-alert", json={"repetitions": 1}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_rejects_non_json_actions(client):
    r = client.post("/api/actions/test-alert", content=b'{"repetitions": 1}', headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


def test_rejects_foreign_host_header():
    r = TestClient(dashboard_app.app, base_url="http://evil.example").get("/api/status")
    assert r.status_code == 400


def test_rejects_bad_log_range(client):
    r = client.get("/api/logs?minutes=abc")
    assert r.status_code == 400 and r.json()["ok"] is False


def test_test_alert_is_clamped_to_ten_messages(client, monkeypatch):
    calls = []
    monkeypatch.setattr(aws_bot, "invoke", lambda payload: calls.append(payload) or {"ok": True, "result": {}})
    r = client.post("/api/actions/test-alert", json={"repetitions": 50},
                    headers={"Origin": "http://127.0.0.1:8765"})
    assert r.status_code == 200
    assert calls == [{"test": True, "repetitions": 10}]
