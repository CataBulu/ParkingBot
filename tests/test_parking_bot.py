"""Behaviour of the Lambda bot (parking_bot.py) against a fake parking site, SSM and Telegram."""
import io
import json
import urllib.error

import pytest

import parking_bot

# Fake personal data: the privacy test checks that none of it ever reaches Telegram.
ADDRESS = "Test Street 1, Block 9"
RESIDENCE_ID = 4242
LOT_NAME = "Block 9 Parking"


class FakeSSM:
    class exceptions:
        class ParameterNotFound(Exception):
            pass

    def __init__(self):
        self.store = {}

    def get_parameter(self, Name):
        if Name not in self.store:
            raise self.exceptions.ParameterNotFound()
        return {"Parameter": {"Value": self.store[Name]}}

    def put_parameter(self, Name, Value, **kwargs):
        assert kwargs["Overwrite"] is True
        self.store[Name] = Value


class FakeSite:
    """Answers the same API calls as the real portal."""

    def __init__(self):
        self.lots = []
        self.login_status = 200
        self.auctions = {"auctions_registrations": [], "waitlist": []}

    def call(self, api, method, path, body=None):
        if path == "person/login":
            assert body == {"EMAIL": "user@example.com", "password": "secret"}
            if self.login_status != 200:
                raise urllib.error.HTTPError(path, self.login_status, "error", {}, io.BytesIO())
            return {"_id": "user"}
        if path == "person":
            return {"address": [{"_id": "a1", "ID_IMOBIL": RESIDENCE_ID}]}
        if path == f"immobile/{RESIDENCE_ID}?distance_to_parking_lot=30":
            return {"full_name": ADDRESS, "parking_lots": self.lots}
        if path == "auctions":
            return self.auctions
        raise AssertionError(f"unexpected API call: {method} {path}")


def spot(number, availability="free", status="active"):
    return {"id": 100 + number, "number": number, "availability": availability, "status": status}


def open_lot(*spots, session_open=True):
    return {"id": 5, "name": LOT_NAME, "can_apply_for_auction": session_open,
            "can_apply_for_waitlist": False, "residence_parking_spots": list(spots)}


class Harness:
    def __init__(self, monkeypatch):
        self.ssm = FakeSSM()
        self.site = FakeSite()
        self.sent = []
        self.all_sent = []
        monkeypatch.setattr(parking_bot, "ssm", self.ssm)
        monkeypatch.setattr(parking_bot, "send_telegram", self._send)
        monkeypatch.setattr(parking_bot.time, "sleep", lambda seconds: None)
        monkeypatch.setattr(parking_bot.ParkoApi, "call",
                            lambda api, method, path, body=None: self.site.call(api, method, path, body))

    def _send(self, message):
        self.sent.append(message)
        self.all_sent.append(message)

    def run(self, event=None):
        self.sent = []
        return parking_bot.handler(event or {}, None)

    @property
    def saved(self):
        return json.loads(self.ssm.store[parking_bot.SSM_STATE_KEY])


@pytest.fixture
def bot(monkeypatch):
    return Harness(monkeypatch)


@pytest.fixture
def running_bot(bot):
    """A bot that has already completed its first run."""
    bot.run()
    return bot


def test_first_run_saves_state_and_announces(bot):
    result = bot.run()
    assert result["statusCode"] == 200 and "First run" in result["body"]
    assert len(bot.sent) == 1 and "started" in bot.sent[0]
    assert bot.saved["errors"] == 0
    assert str(RESIDENCE_ID) in bot.saved["state"]["residences"]


def test_no_change_is_silent(running_bot):
    running_bot.run()
    assert running_bot.sent == []


def test_session_opening_sends_ten_urgent_alerts(running_bot):
    running_bot.site.lots = [open_lot(spot(1), spot(2), spot(3, "occupied"), spot(4, status="inactive"))]
    running_bot.run()
    assert len(running_bot.sent) == parking_bot.REPETITIONS == 10
    first = running_bot.sent[0]
    assert "[1/10] PARKING ALERT" in first
    assert "Submission session OPEN" in first
    assert "+2</b> new free spot(s)" in first and ": 1, 2" in first  # occupied / inactive spots excluded


def test_spot_taken_then_freed_alerts_again(running_bot):
    running_bot.site.lots = [open_lot(spot(1))]
    running_bot.run()
    running_bot.site.lots = [open_lot(spot(1, "occupied"))]
    running_bot.run()
    assert running_bot.sent == []  # a spot being taken is not an alert
    running_bot.site.lots = [open_lot(spot(1))]
    running_bot.run()
    assert len(running_bot.sent) == 10 and "+1</b>" in running_bot.sent[0]


def test_registration_change_sends_one_info_message(running_bot):
    running_bot.site.auctions = {"auctions_registrations": [{"id": 9}], "waitlist": []}
    running_bot.run()
    assert len(running_bot.sent) == 1
    assert "registrations changed: 1 auctions" in running_bot.sent[0]


def test_login_failure_warns_once_after_three_runs(running_bot):
    running_bot.site.login_status = 401
    for attempt in range(1, 5):
        with pytest.raises(parking_bot.LoginError):
            running_bot.run()
        assert running_bot.saved["errors"] == attempt
        if attempt == parking_bot.ERROR_THRESHOLD:
            assert len(running_bot.sent) == 1 and "Login failed: wrong password" in running_bot.sent[0]
        else:
            assert running_bot.sent == []


def test_recovery_after_warning_resets_the_counter(running_bot):
    running_bot.site.login_status = 401
    for _ in range(parking_bot.ERROR_THRESHOLD):
        with pytest.raises(parking_bot.LoginError):
            running_bot.run()
    running_bot.site.login_status = 200
    running_bot.run()
    assert running_bot.sent == ["✅ Parking Bot is working again."]
    assert running_bot.saved["errors"] == 0
    running_bot.run()
    assert running_bot.sent == []


def test_test_mode_sends_labelled_alerts_without_saving(running_bot):
    before = dict(running_bot.ssm.store)
    result = running_bot.run({"test": True, "repetitions": 3})
    assert len(running_bot.sent) == 3
    assert all("🧪 TEST [" in m and "This is a TEST" in m for m in running_bot.sent)
    assert running_bot.ssm.store == before
    assert "TEST sent (3 messages)" in result["body"]
    running_bot.run()
    assert running_bot.sent == []  # the next scheduled run sees no change


def test_messages_never_contain_personal_data(running_bot):
    running_bot.site.lots = [open_lot(spot(1), spot(2))]
    running_bot.run()
    running_bot.site.lots = []
    running_bot.run()
    running_bot.run({"test": True})
    assert running_bot.all_sent
    for message in running_bot.all_sent:
        for private in (ADDRESS, str(RESIDENCE_ID), LOT_NAME):
            assert private not in message, f"{private!r} leaked into: {message}"


class UnexpectedError(Exception):
    pass


@pytest.mark.parametrize("error, expected", [
    (parking_bot.LoginError("Login failed: wrong password"), "Login failed: wrong password"),
    (urllib.error.HTTPError("url", 500, "boom", {}, io.BytesIO()), "HTTP 500 from the parking site"),
    (urllib.error.URLError("no route"), "Parking site unreachable"),
    (UnexpectedError(f"GET /api/immobile/{RESIDENCE_ID} failed for {ADDRESS}"), "UnexpectedError"),
])
def test_safe_error_hides_request_details(error, expected):
    assert parking_bot.safe_error(error) == expected
