"""
Bot Parcare Craiova - varianta API (fara browser, fara Docker).

La fiecare rulare (EventBridge, la 10 minute):
  1. Login pe API-ul Parko Manager            POST /api/person/login
  2. Imobilele contului                        GET  /api/person  -> address[].ID_IMOBIL
  3. Parcarile din jurul fiecarui imobil       GET  /api/immobile/{id}?distance_to_parking_lot=30
  4. Inscrierile la licitatii / asteptare      GET  /api/auctions
  5. Compara cu starea salvata in SSM si trimite alerte Telegram la schimbari

Un loc e considerat LIBER exact ca pe site (verde pe harta):
    availability == "free" and status == "active"
Sesiunea de depunere e DESCHISA pentru o parcare cand:
    can_apply_for_auction == True

Test manual al alertelor (date reale + o parcare simulata, nu salveaza nimic):
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
#  CONFIGURARE (din Environment Variables Lambda)
# ─────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SITE_EMAIL       = os.environ["SITE_EMAIL"]
SITE_PASSWORD    = os.environ["SITE_PASSWORD"]

SITE          = "https://parcari-ticketing.primariacraiova.ro"
API           = SITE + "/api/"
DISTANTA_M    = 30                      # aceeasi distanta ca pe site
SSM_STATE_KEY = "/bot-parcare/state"
PRAG_ERORI    = 3                       # alerta dupa 3 rulari esuate la rand (~30 min)
NR_REPETARI   = 10                      # alertele urgente se repeta de 10 ori, la 3 sec

ssm = boto3.client("ssm")

# ─────────────────────────────────────────
#  CLIENT API (cookie de sesiune, ca browserul)
# ─────────────────────────────────────────
class EroareLogin(Exception):
    pass


class ApiParko:
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
                "User-Agent": "Mozilla/5.0 (bot-parcare-craiova)",
            },
        )
        with self.opener.open(req, timeout=20) as resp:
            text = resp.read().decode("utf-8")
            return json.loads(text) if text.strip() else None

    def login(self):
        try:
            self.call("POST", "person/login", {"EMAIL": SITE_EMAIL, "password": SITE_PASSWORD})
        except urllib.error.HTTPError as e:
            motiv = {401: "parola gresita", 403: "email-ul nu exista"}.get(e.code, f"HTTP {e.code}")
            raise EroareLogin(f"Login esuat: {motiv}") from e


# ─────────────────────────────────────────
#  CITIRE STARE CURENTA
# ─────────────────────────────────────────
def amprenta(obj) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:12]


def citeste_starea() -> dict:
    api = ApiParko()
    api.login()

    person = api.call("GET", "person") or {}
    ids_imobile = sorted({str(a["ID_IMOBIL"]) for a in person.get("address") or [] if a.get("ID_IMOBIL")})
    if not ids_imobile:
        raise RuntimeError("Contul nu are niciun imobil (address[].ID_IMOBIL) - verifica pe site.")

    imobile = {}
    for id_imobil in ids_imobile:
        info = api.call("GET", f"immobile/{id_imobil}?distance_to_parking_lot={DISTANTA_M}") or {}
        parcari = {}
        for lot in info.get("parking_lots") or []:
            spots = lot.get("residence_parking_spots") or []
            parcari[str(lot.get("id"))] = {
                "nume": lot.get("name") or f"Parcarea {lot.get('id')}",
                "licitatie": lot.get("can_apply_for_auction") is True,
                "asteptare": bool(lot.get("can_apply_for_waitlist")),
                "total": len(spots),
                "libere": sorted(
                    str(s["number"] if s.get("number") is not None else s.get("id"))
                    for s in spots
                    if s.get("availability") == "free" and s.get("status") == "active"
                ),
            }
        imobile[id_imobil] = {
            "nume": info.get("full_name") or info.get("name") or f"Imobil {id_imobil}",
            "parcari": parcari,
        }

    auctions = api.call("GET", "auctions") or {}
    inscrieri = {
        "licitatii": len(auctions.get("auctions_registrations") or []),
        "asteptare": len(auctions.get("waitlist") or []),
        "amprenta": amprenta(auctions),
    }
    return {"imobile": imobile, "inscrieri": inscrieri}


# ─────────────────────────────────────────
#  COMPARARE -> ALERTE
# ─────────────────────────────────────────
def compara(vechi: dict, nou: dict) -> tuple[list[str], list[str]]:
    """Returneaza (alerte_urgente, alerte_info)."""
    urgente, info = [], []
    e = html.escape

    for id_imobil, imobil in nou["imobile"].items():
        imobil_vechi = vechi["imobile"].get(id_imobil)
        if imobil_vechi is None:
            info.append(f"🏠 Imobil nou in cont: {e(imobil['nume'])}")
            imobil_vechi = {"parcari": {}}

        for lot_id, lot in imobil["parcari"].items():
            lot_vechi = imobil_vechi["parcari"].get(lot_id)
            nume = e(lot["nume"])
            if lot["licitatie"] and not (lot_vechi and lot_vechi["licitatie"]):
                urgente.append(f"📢 S-a DESCHIS sesiunea de depunere pentru <b>{nume}</b>!")
            libere_noi = sorted(set(lot["libere"]) - set(lot_vechi["libere"] if lot_vechi else []))
            if libere_noi:
                urgente.append(
                    f"🅿️ <b>+{len(libere_noi)}</b> loc(uri) liber(e) in <b>{nume}</b>: {e(', '.join(libere_noi))}"
                )
            if lot_vechi is None:
                info.append(f"🆕 Parcare noua langa {e(imobil['nume'])}: {nume} ({lot['total']} locuri)")
            if lot["asteptare"] and not (lot_vechi and lot_vechi["asteptare"]):
                info.append(f"📝 Te poti inscrie pe lista de asteptare pentru {nume}.")

        for lot_id, lot_vechi in imobil_vechi["parcari"].items():
            if lot_id not in imobil["parcari"]:
                info.append(f"➖ {e(lot_vechi['nume'])} nu mai apare langa {e(imobil['nume'])}.")

    if nou["inscrieri"]["amprenta"] != vechi["inscrieri"]["amprenta"]:
        i = nou["inscrieri"]
        info.append(
            f"📋 S-au schimbat inscrierile tale: {i['licitatii']} la licitatii, "
            f"{i['asteptare']} pe lista de asteptare."
        )
    return urgente, info


def rezumat(stare: dict) -> str:
    randuri = []
    for imobil in stare["imobile"].values():
        parcari = imobil["parcari"]
        randuri.append(f"🏠 {html.escape(imobil['nume'])}: {len(parcari)} parcari in {DISTANTA_M} m")
        for lot in parcari.values():
            sesiune = "DESCHISA" if lot["licitatie"] else "inchisa"
            randuri.append(
                f"   • {html.escape(lot['nume'])}: {len(lot['libere'])}/{lot['total']} libere, sesiune {sesiune}"
            )
    i = stare["inscrieri"]
    randuri.append(f"📋 Inscrieri: {i['licitatii']} licitatii, {i['asteptare']} lista de asteptare")
    return "\n".join(randuri)


# ─────────────────────────────────────────
#  SSM + TELEGRAM
# ─────────────────────────────────────────
def citeste_ssm() -> dict:
    try:
        return json.loads(ssm.get_parameter(Name=SSM_STATE_KEY)["Parameter"]["Value"])
    except ssm.exceptions.ParameterNotFound:
        return {}


def salveaza_ssm(date: dict):
    ssm.put_parameter(
        Name=SSM_STATE_KEY,
        Value=json.dumps(date, ensure_ascii=False, separators=(",", ":")),
        Type="String",
        Tier="Intelligent-Tiering",
        Overwrite=True,
    )


def send_telegram(mesaj: str):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        data=json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": mesaj, "parse_mode": "HTML",
                         "disable_web_page_preview": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except Exception as e:
        logger.error(f"Eroare Telegram: {e}")


def trimite_alerte(urgente: list[str], info: list[str], repetari: int = NR_REPETARI, eticheta: str = ""):
    if urgente:
        corp = "\n".join(urgente + info)
        for i in range(repetari):
            send_telegram(
                f"🚨 <b>{eticheta}[{i + 1}/{repetari}] ALERTĂ PARCARE CRAIOVA!</b>\n\n{corp}\n\n"
                f"⚡ Intră RAPID: {SITE}"
            )
            if i < repetari - 1:
                time.sleep(3)
    elif info:
        send_telegram(f"ℹ️ <b>{eticheta}Bot Parcare - schimbare</b>\n\n" + "\n".join(info) + f"\n\n{SITE}")


def ruleaza_test(event: dict) -> dict:
    """Alerta de TEST: login + date reale, plus o parcare simulata langa primul imobil. Nu salveaza nimic."""
    stare = citeste_starea()
    simulat = copy.deepcopy(stare)
    imobil = next(iter(simulat["imobile"].values()))
    imobil["parcari"]["test"] = {
        "nume": "PARCARE TEST (simulare)", "licitatie": True, "asteptare": False,
        "total": 3, "libere": ["1", "2"],
    }
    urgente, info = compara(stare, simulat)
    repetari = int(event.get("repetari", 3))
    trimite_alerte(urgente, info + ["🧪 <i>Acesta este un TEST - pe site nu s-a schimbat nimic.</i>"],
                   repetari, "🧪 TEST ")
    body = f"TEST trimis ({repetari} mesaje) | " + rezumat(stare).replace("\n", " | ")
    logger.info(body)
    return {"statusCode": 200, "body": body}


# ─────────────────────────────────────────
#  HANDLER PRINCIPAL LAMBDA
# ─────────────────────────────────────────
def handler(event, context):
    if isinstance(event, dict) and event.get("test"):
        return ruleaza_test(event)

    salvat = citeste_ssm()
    erori = salvat.get("erori", 0)

    try:
        stare = citeste_starea()
    except Exception as e:
        erori += 1
        logger.exception(f"Verificare esuata ({erori} la rand)")
        if erori == PRAG_ERORI:
            send_telegram(
                f"⚠️ <b>Bot Parcare: nu mai pot verifica site-ul</b> ({erori} incercari la rand).\n"
                f"Ultima eroare: <code>{html.escape(str(e)[:300])}</code>\n"
                f"Te anunt cand merge din nou."
            )
        salveaza_ssm({**salvat, "erori": erori})
        raise  # Lambda marcheaza rularea ca Error (vizibil in CloudWatch)

    if erori >= PRAG_ERORI:
        send_telegram("✅ Bot Parcare functioneaza din nou.")

    vechi = salvat.get("stare")
    if vechi is None:
        send_telegram(
            "<b>🤖 Bot Parcare Craiova pornit (varianta API)</b>\n\n"
            f"{rezumat(stare)}\n\n"
            "🔍 Verific la fiecare 10 minute si te anunt cand se deschide o sesiune "
            "sau apar locuri libere."
        )
        salveaza_ssm({"stare": stare, "erori": 0})
        logger.info(f"Prima rulare. Stare initiala: {json.dumps(stare, ensure_ascii=False)}")
        return {"statusCode": 200, "body": "Prima rulare - stare initiala salvata."}

    urgente, info = compara(vechi, stare)
    trimite_alerte(urgente, info)

    if stare != vechi or erori:
        salveaza_ssm({"stare": stare, "erori": 0})

    body = f"urgente={len(urgente)} info={len(info)} | " + rezumat(stare).replace("\n", " | ")
    logger.info(body)
    return {"statusCode": 200, "body": body}
