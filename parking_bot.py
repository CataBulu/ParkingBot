"""
Craiova Parking Bot - API version (no browser, no Docker).

On every run (EventBridge, every 10 minutes):
  1. Log in to the Parko Manager API            POST /api/person/login
  2. Read the account's residences              GET  /api/person  -> address[].ID_IMOBIL
  3. Read parking lots around each residence    GET  /api/immobile/{id}?distance_to_parking_lot=30
  4. Read auction / waitlist registrations      GET  /api/auctions
  5. Compare with the state saved in SSM and send Telegram alerts on changes

A spot counts as FREE exactly like on the site (green on the map):
    availability == "free" and status == "active"
The submission session is OPEN for a parking lot when:
    can_apply_for_auction == True

Manual alert test (real data + one simulated parking lot, saves nothing):
    aws lambda invoke --function-name bot-parcare-craiova-api --payload '{"test": true}' ...
"""
import copy
import hashlib
import html
import http.cookiejar
import json
import logging
import os
import time
import urllib.error
import urllib.request

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ─────────────────────────────────────────
#  CONFIGURATION (Lambda environment variables)
# ─────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SITE_EMAIL       = os.environ["SITE_EMAIL"]
SITE_PASSWORD    = os.environ["SITE_PASSWORD"]

SITE            = "https://parcari-ticketing.primariacraiova.ro"
API             = SITE + "/api/"
DISTANCE_M      = 30                    # same distance the site uses
SSM_STATE_KEY   = "/bot-parcare/state"
ERROR_THRESHOLD = 3                     # warn after 3 failed runs in a row (~30 min)
REPETITIONS     = 10                    # urgent alerts are repeated 10 times, 3 s apart

ssm = boto3.client("ssm")

# ─────────────────────────────────────────
#  API CLIENT (session cookie, like the browser)
# ─────────────────────────────────────────
class LoginError(Exception):
    pass


class ParkoApi:
    def __init__(self):
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def call(self, method: str, path: str, body=None):
        req = urllib.request.Request(
            API + path,
            data=json.dumps(body).encode() if body is not None else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Origin": SITE,
                "Referer": SITE + "/",
                "User-Agent": "Mozilla/5.0 (parking-bot)",
            },
        )
        with self.opener.open(req, timeout=20) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text.strip() else None

    def login(self):
        try:
            self.call("POST", "person/login", {"EMAIL": SITE_EMAIL, "password": SITE_PASSWORD})
        except urllib.error.HTTPError as e:
            reason = {401: "wrong password", 403: "email not found"}.get(e.code, f"HTTP {e.code}")
            raise LoginError(f"Login failed: {reason}") from e


# ─────────────────────────────────────────
#  READ CURRENT STATE
# ─────────────────────────────────────────
def fingerprint(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


def read_state() -> dict:
    api = ParkoApi()
    api.login()

    person = api.call("GET", "person") or {}
    residence_ids = sorted({str(a["ID_IMOBIL"]) for a in person.get("address") or [] if a.get("ID_IMOBIL")})
    if not residence_ids:
        raise RuntimeError("The account has no residence (address[].ID_IMOBIL) - check the site.")

    residences = {}
    for residence_id in residence_ids:
        info = api.call("GET", f"immobile/{residence_id}?distance_to_parking_lot={DISTANCE_M}") or {}
        lots = {}
        for lot in info.get("parking_lots") or []:
            spots = lot.get("residence_parking_spots") or []
            lots[str(lot.get("id"))] = {
                "name": lot.get("name") or f"Parking lot {lot.get('id')}",
                "session_open": lot.get("can_apply_for_auction") is True,
                "waitlist_open": bool(lot.get("can_apply_for_waitlist")),
                "total": len(spots),
                "free": sorted(
                    str(s["number"] if s.get("number") is not None else s.get("id"))
                    for s in spots
                    if s.get("availability") == "free" and s.get("status") == "active"
                ),
            }
        residences[residence_id] = {
            "name": info.get("full_name") or info.get("name") or f"Residence {residence_id}",
            "lots": lots,
        }

    auctions = api.call("GET", "auctions") or {}
    registrations = {
        "auctions": len(auctions.get("auctions_registrations") or []),
        "waitlist": len(auctions.get("waitlist") or []),
        "fingerprint": fingerprint(auctions),
    }
    return {"residences": residences, "registrations": registrations}


# ─────────────────────────────────────────
#  COMPARE -> ALERTS
#  Messages and logs never contain the address, residence ID or parking lot names:
#  residences and lots get neutral labels ("your residence", "parking lot 1").
# ─────────────────────────────────────────
def labels(state: dict) -> tuple[dict, dict]:
    """Returns ({residence_id: label}, {(residence_id, lot_id): label}), stable for a given state."""
    residence_ids = sorted(state["residences"])
    residences = {rid: "your residence" if len(residence_ids) == 1 else f"residence {i}"
                  for i, rid in enumerate(residence_ids, 1)}
    lots, n = {}, 0
    for rid in residence_ids:
        for lot_id in sorted(state["residences"][rid]["lots"]):
            n += 1
            lots[(rid, lot_id)] = f"parking lot {n}"
    return residences, lots


def compare(old: dict, new: dict) -> tuple[list[str], list[str]]:
    """Returns (urgent_alerts, info_alerts)."""
    urgent, info = [], []
    residence_labels, lot_labels = labels(new)
    _, old_lot_labels = labels(old)

    for residence_id, residence in new["residences"].items():
        where = residence_labels[residence_id]
        old_residence = old["residences"].get(residence_id)
        if old_residence is None:
            info.append("🏠 A new residence was added to the account.")
            old_residence = {"lots": {}}

        for lot_id, lot in residence["lots"].items():
            old_lot = old_residence["lots"].get(lot_id)
            name = lot_labels[(residence_id, lot_id)]
            if lot["session_open"] and not (old_lot and old_lot["session_open"]):
                urgent.append(f"📢 Submission session OPEN for <b>{name}</b> near {where}!")
            new_free = sorted(set(lot["free"]) - set(old_lot["free"] if old_lot else []))
            if new_free:
                urgent.append(f"🅿️ <b>+{len(new_free)}</b> new free spot(s) in <b>{name}</b>: "
                              f"{html.escape(', '.join(new_free))}")
            if old_lot is None:
                info.append(f"🆕 New parking lot near {where}: {name} ({lot['total']} spots)")
            if lot["waitlist_open"] and not (old_lot and old_lot["waitlist_open"]):
                info.append(f"📝 Waitlist open for {name}.")

        for lot_id in old_residence["lots"]:
            if lot_id not in residence["lots"]:
                info.append(f"➖ A parking lot is no longer listed near {where} "
                            f"(was {old_lot_labels.get((residence_id, lot_id), 'a lot')}).")

    if new["registrations"]["fingerprint"] != old["registrations"]["fingerprint"]:
        r = new["registrations"]
        info.append(f"📋 Your registrations changed: {r['auctions']} auctions, {r['waitlist']} on the waitlist.")
    return urgent, info


def summary(state: dict) -> str:
    residence_labels, lot_labels = labels(state)
    lines = []
    for residence_id, residence in state["residences"].items():
        lots = residence["lots"]
        lines.append(f"🏠 {residence_labels[residence_id].capitalize()}: "
                     f"{len(lots)} parking lots within {DISTANCE_M} m")
        for lot_id, lot in lots.items():
            session = "OPEN" if lot["session_open"] else "closed"
            lines.append(f"   • {lot_labels[(residence_id, lot_id)]}: "
                         f"{len(lot['free'])}/{lot['total']} free, session {session}")
    r = state["registrations"]
    lines.append(f"📋 Registrations: {r['auctions']} auctions, {r['waitlist']} waitlist")
    return "\n".join(lines)


def safe_error(e: Exception) -> str:
    """Error description for Telegram without request details (URLs, IDs, response bodies)."""
    if isinstance(e, (LoginError, RuntimeError)) and type(e) in (LoginError, RuntimeError):
        return str(e)  # our own messages, no personal data
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code} from the parking site"
    if isinstance(e, urllib.error.URLError):
        return "Parking site unreachable"
    return type(e).__name__


# ─────────────────────────────────────────
#  SSM + TELEGRAM
# ─────────────────────────────────────────
def load_saved() -> dict:
    try:
        return json.loads(ssm.get_parameter(Name=SSM_STATE_KEY)["Parameter"]["Value"])
    except ssm.exceptions.ParameterNotFound:
        return {}


def save(data: dict):
    ssm.put_parameter(
        Name=SSM_STATE_KEY,
        Value=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        Type="String",
        Tier="Intelligent-Tiering",
        Overwrite=True,
    )


def send_telegram(message: str):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML",
                         "disable_web_page_preview": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        logger.error(f"Telegram error: {e}")


def send_alerts(urgent: list[str], info: list[str], repetitions: int = REPETITIONS, label: str = ""):
    if urgent:
        body = "\n".join(urgent + info)
        for i in range(repetitions):
            send_telegram(
                f"🚨 <b>{label}[{i + 1}/{repetitions}] PARKING ALERT - CRAIOVA!</b>\n\n{body}\n\n"
                f"⚡ Go now: {SITE}"
            )
            if i < repetitions - 1:
                time.sleep(3)
    elif info:
        send_telegram(f"ℹ️ <b>{label}Parking Bot - change</b>\n\n" + "\n".join(info) + f"\n\n{SITE}")


def run_test(event: dict) -> dict:
    """TEST alert: real login + data, plus one simulated lot next to the first residence. Saves nothing."""
    state = read_state()
    simulated = copy.deepcopy(state)
    residence = next(iter(simulated["residences"].values()))
    residence["lots"]["test"] = {
        "name": "TEST PARKING LOT (simulated)", "session_open": True, "waitlist_open": False,
        "total": 3, "free": ["1", "2"],
    }
    urgent, info = compare(state, simulated)
    repetitions = int(event.get("repetitions", 3))
    send_alerts(urgent, info + ["🧪 <i>This is a TEST - nothing changed on the site.</i>"],
                repetitions, "🧪 TEST ")
    body = f"TEST sent ({repetitions} messages) | " + summary(state).replace("\n", " | ")
    logger.info(body)
    return {"statusCode": 200, "body": body}


# ─────────────────────────────────────────
#  LAMBDA HANDLER
# ─────────────────────────────────────────
def handler(event, context):
    if isinstance(event, dict) and event.get("test"):
        return run_test(event)

    saved = load_saved()
    errors = saved.get("errors", 0)

    try:
        state = read_state()
    except Exception as e:
        errors += 1
        logger.exception(f"Check failed ({errors} in a row)")
        if errors == ERROR_THRESHOLD:
            send_telegram(
                f"⚠️ <b>Parking Bot: can't check the site</b> ({errors} attempts in a row).\n"
                f"Last error: <code>{html.escape(safe_error(e))}</code>\n"
                f"I'll let you know when it works again."
            )
        save({**saved, "errors": errors})
        raise  # Lambda marks the run as an Error (visible in CloudWatch)

    if errors >= ERROR_THRESHOLD:
        send_telegram("✅ Parking Bot is working again.")

    old = saved.get("state")
    if old is None:
        send_telegram(
            "<b>🤖 Craiova Parking Bot started</b>\n\n"
            f"{summary(state)}\n\n"
            "🔍 Checking every 10 minutes. You'll be alerted when a submission session opens "
            "or free spots appear."
        )
        save({"state": state, "errors": 0})
        logger.info("First run. Initial state: " + summary(state).replace("\n", " | "))
        return {"statusCode": 200, "body": "First run - initial state saved."}

    urgent, info = compare(old, state)
    send_alerts(urgent, info)

    if state != old or errors:
        save({"state": state, "errors": 0})

    body = f"urgent={len(urgent)} info={len(info)} | " + summary(state).replace("\n", " | ")
    logger.info(body)
    return {"statusCode": 200, "body": body}
