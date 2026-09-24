import os
import time
import logging
import requests
import boto3
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

# ─────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
#  CONFIGURARE (din Environment Variables Lambda)
# ─────────────────────────────────────────
TELEGRAM_TOKEN   = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SITE_EMAIL       = os.environ["SITE_EMAIL"]
SITE_PASSWORD    = os.environ["SITE_PASSWORD"]
AWS_REGION       = os.environ.get("AWS_DEFAULT_REGION", "eu-central-1")

# ─────────────────────────────────────────
#  CONSTANTE SITE
# ─────────────────────────────────────────
URL_LOGIN = "https://parcari-ticketing.primariacraiova.ro/login"

# XPath poligoane strict din interiorul hartii Leaflet
XPATH_POLIGOANE = (
    "//div[contains(@class,'leaflet-container')]"
    "//*[local-name()='svg']"
    "//*[local-name()='path' or local-name()='polygon']"
)

# Cheia SSM unde salvam baseline-ul intre rulari
SSM_BASELINE_KEY = "/bot-parcare/baseline"

# ─────────────────────────────────────────
#  SSM HELPERS  (memoria persistenta a botului)
# ─────────────────────────────────────────
ssm = boto3.client("ssm", region_name=AWS_REGION)

def get_baseline():
    """Citeste baseline-ul salvat din SSM. Returneaza None la prima rulare."""
    try:
        resp = ssm.get_parameter(Name=SSM_BASELINE_KEY)
        return int(resp["Parameter"]["Value"])
    except ssm.exceptions.ParameterNotFound:
        return None
    except Exception as e:
        logger.error(f"Eroare SSM get: {e}")
        return None

def save_baseline(count: int):
    """Salveaza noul baseline in SSM (suprascrie valoarea veche)."""
    try:
        ssm.put_parameter(
            Name=SSM_BASELINE_KEY,
            Value=str(count),
            Type="String",
            Overwrite=True,
        )
        logger.info(f"Baseline salvat in SSM: {count}")
    except Exception as e:
        logger.error(f"Eroare SSM put: {e}")

# ─────────────────────────────────────────
#  TELEGRAM HELPER
# ─────────────────────────────────────────
def send_telegram(mesaj: str):
    """Trimite un mesaj pe botul de Telegram."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": mesaj, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Mesaj Telegram trimis.")
    except Exception as e:
        logger.error(f"Eroare Telegram: {e}")

# ─────────────────────────────────────────
#  POPUP / MODAL DISMISSAL
# ─────────────────────────────────────────
def inchide_popup(page) -> bool:
    """
    Detecteaza si inchide orice dialog modal MUI care ar putea bloca pagina
    (ex: consimtamant cookie-uri, anunturi). Returneaza True daca a gasit unul.

    Strategie (in ordine):
      1. Logheaza textul + butoanele popup-ului (diagnostic)
      2. Click pe butoane comune de accept/inchide (RO + EN)
      3. Click pe butonul X (icon de inchidere)
      4. Apasa Escape
      5. Fallback dur: sterge overlay-ul din DOM
    """
    try:
        dialog = page.locator(".MuiDialog-root, .MuiModal-root, [role='dialog']").first
        if dialog.count() == 0:
            return False

        # ─── Diagnostic: ce contine popup-ul ───
        try:
            txt = dialog.inner_text(timeout=2_000)
            print(f">>> POPUP detectat. Text: {txt[:400]}", flush=True)
        except Exception:
            print(">>> POPUP detectat (nu am putut citi textul).", flush=True)
        try:
            nume_btn = []
            for b in dialog.locator("button").all():
                try:
                    nume_btn.append((b.inner_text() or b.get_attribute("aria-label") or "?").strip())
                except Exception:
                    nume_btn.append("?")
            print(f">>> Butoane in popup: {nume_btn}", flush=True)
        except Exception:
            pass

        # ─── 1) Butoane comune accept/inchide ───
        etichete = [
            "Acceptă toate", "Accepta toate", "Acceptă", "Accepta", "Accept",
            "De acord", "Sunt de acord", "Am înțeles", "Am inteles",
            "Continuă", "Continua", "Permite", "OK", "Ok",
            "Închide", "Inchide", "Da",
        ]
        for et in etichete:
            try:
                b = dialog.get_by_role("button", name=et, exact=False)
                if b.count() > 0:
                    b.first.click(timeout=2_000)
                    print(f">>> Popup inchis cu butonul: '{et}'", flush=True)
                    page.wait_for_timeout(800)
                    return True
            except Exception:
                continue

        # ─── 2) Buton X (icon de inchidere) ───
        try:
            x = dialog.locator(
                "button[aria-label*='close' i], button[aria-label*='nchide' i], .MuiIconButton-root"
            )
            if x.count() > 0:
                x.first.click(timeout=2_000)
                print(">>> Popup inchis cu butonul X.", flush=True)
                page.wait_for_timeout(800)
                return True
        except Exception:
            pass

        # ─── 3) Escape ───
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            print(">>> Popup: am apasat Escape.", flush=True)
        except Exception:
            pass

        # ─── 4) Fallback dur: stergem overlay-ul din DOM ───
        try:
            page.evaluate(
                "() => { document.querySelectorAll("
                "'.MuiBackdrop-root, .MuiDialog-root, .MuiModal-root')"
                ".forEach(e => e.remove()); }"
            )
            print(">>> Popup: am sters overlay-ul din DOM (fallback).", flush=True)
            page.wait_for_timeout(300)
        except Exception:
            pass
        return True

    except Exception as e:
        print(f">>> inchide_popup eroare: {e}", flush=True)
        return False

# ─────────────────────────────────────────
#  BROWSER AUTOMATION  (Playwright headless)
# ─────────────────────────────────────────
def numara_locuri_parcare() -> int:
    """
    Deschide Chromium headless, se logheaza automat, navigheaza
    prin meniu pana la harta Leaflet si numara poligoanele SVG.
    Returneaza numarul de poligoane gasite.
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-gpu-sandbox",
                "--in-process-gpu",        # GPU ruleaza in procesul principal, nu separat
                "--single-process",        # fara procese copil (obligatoriu in Lambda)
                "--no-zygote",             # fara zygote process (obligatoriu in Lambda)
                "--disable-extensions",
                "--disable-software-rasterizer",
                "--font-render-hinting=none",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.set_default_timeout(30_000)

        try:
            # ─── PAS 1: LOGIN ───────────────────────────────
            print(">>> Navighez la pagina de login...", flush=True)
            page.goto(URL_LOGIN, wait_until="domcontentloaded")

            print(">>> Astept React sa randeze (5 sec)...", flush=True)
            page.wait_for_timeout(5_000)
            print(f">>> URL: {page.url}", flush=True)
            print(f">>> Title: {page.title()}", flush=True)

            # Inchidem orice popup aparut la incarcare (ex: consimtamant cookie-uri)
            inchide_popup(page)

            # Vedem ce e pe pagina
            try:
                body_text = page.locator("body").inner_text()
                print(f">>> Body text (500 chars): {body_text[:500]}", flush=True)
            except Exception as be:
                print(f">>> Body text eroare: {be}", flush=True)

            # Numaram si afisam toate inputurile gasite
            try:
                inputs = page.locator("input").all()
                print(f">>> Input-uri gasite: {len(inputs)}", flush=True)
                for i, inp in enumerate(inputs):
                    t = inp.get_attribute("type") or "?"
                    n = inp.get_attribute("name") or "?"
                    print(f"    Input[{i}]: type={t}, name={n}", flush=True)
            except Exception as ie:
                print(f">>> Eroare la listarea inputurilor: {ie}", flush=True)

            print(">>> Completez email si parola...", flush=True)
            # Incercam mai multi selectori in ordine
            email_selectors = [
                'input[type="email"]',
                'input[name="email"]',
                'input[type="text"]',
            ]
            email_filled = False
            for sel in email_selectors:
                try:
                    page.locator(sel).first.fill(SITE_EMAIL, timeout=5_000)
                    print(f">>> Email completat cu selectorul: {sel}", flush=True)
                    email_filled = True
                    break
                except Exception:
                    print(f">>> Selector '{sel}' nu a functionat", flush=True)
                    continue

            if not email_filled:
                raise Exception("Nu am putut completa email-ul. Niciun selector nu a functionat.")

            page.locator('input[type="password"]').fill(SITE_PASSWORD, timeout=10_000)

            # Inchidem din nou orice popup care ar putea bloca butonul de login
            inchide_popup(page)

            # Click pe AUTENTIFICARE, cu fallback-uri daca popup-ul reapare
            print(">>> Apas pe AUTENTIFICARE...", flush=True)
            try:
                page.click("#big-white-button", timeout=10_000)
            except Exception as ce:
                print(f">>> Click normal esuat ({ce}). Incerc Enter pe parola...", flush=True)
                try:
                    page.locator('input[type="password"]').press("Enter")
                except Exception:
                    print(">>> Enter esuat. Incerc click fortat...", flush=True)
                    page.locator("#big-white-button").click(force=True, timeout=5_000)

            page.wait_for_load_state("load")
            print(f">>> Login OK. URL curent: {page.url}", flush=True)

            # ─── PAS 2: DASHBOARD → SOLICITARE LOC PARCARE ─
            print(">>> Caut butonul Solicitare Loc Parcare...", flush=True)
            page.locator("button").filter(has_text="Solicitare").first.click()
            page.wait_for_load_state("load")

            # ─── PAS 3: ALEG TIPUL (fara dizabilitati) ─────
            print(">>> Aleg Solicita Loc de Parcare...", flush=True)
            page.locator("button").filter(has_text="Solicită Loc de Parcare").first.click()
            page.wait_for_load_state("load")

            # ─── PAS 4: HARTA LEAFLET ───────────────────────
            print(">>> Astept harta Leaflet...", flush=True)
            page.wait_for_selector(".leaflet-container", timeout=20_000)
            page.wait_for_timeout(5_000)

            count = page.locator(XPATH_POLIGOANE).count()
            print(f">>> Poligoane detectate: {count}", flush=True)
            return count

        except PlaywrightTimeout as e:
            print(f"[ERROR] Timeout browser: {e}", flush=True)
            raise
        except Exception as e:
            print(f"[ERROR] Eroare browser: {e}", flush=True)
            raise
        finally:
            context.close()
            browser.close()

# ─────────────────────────────────────────
#  HANDLER PRINCIPAL LAMBDA
# ─────────────────────────────────────────
def handler(event, context):
    """
    Entry point Lambda.
    Logica:
      - Prima rulare → seteaza baseline, trimite mesaj de confirmare
      - Rulari urmatoare → compara cu baseline
          > mai multe poligoane → 10 alerte Telegram → actualizeaza baseline
          = acelasi numar    → fara actiune, CloudWatch relanseaza in 10 min
    """
    print("=" * 50, flush=True)
    print("BOT PARCARE CRAIOVA - verificare noua", flush=True)
    print("=" * 50, flush=True)

    # ─── Obtine contorul curent ───
    try:
        current_count = numara_locuri_parcare()
    except Exception as e:
        print(f"[ERROR] Eroare fatala: {e}", flush=True)
        return {"statusCode": 500, "body": f"Eroare browser: {str(e)}"}

    # ─── Citeste baseline din SSM ───
    baseline = get_baseline()

    # ─── PRIMA RULARE: seteaza baseline ───────────────────
    if baseline is None:
        save_baseline(current_count)
        send_telegram(
            "<b>🤖 Bot Parcare Craiova pornit!</b>\n\n"
            f"📊 Baseline setat: <b>{current_count}</b> poligoane pe hartă.\n"
            "🔍 Monitorizez automat la fiecare 10 minute.\n"
            "✅ Vei fi alertat imediat când apar locuri noi!"
        )
        logger.info(f"Prima rulare - baseline setat la {current_count}")
        return {"statusCode": 200, "body": f"Prima rulare. Baseline setat: {current_count}"}

    logger.info(f"Comparare: curent={current_count} | baseline={baseline}")

    # ─── LOCURI NOI APARUTE ───────────────────────────────
    if current_count > baseline:
        locuri_noi = current_count - baseline
        logger.info(f"LOCURI NOI DETECTATE! +{locuri_noi} fata de baseline ({baseline})")

        for i in range(10):
            send_telegram(
                f"🚨 <b>[{i+1}/10] ALERTĂ PARCARE CRAIOVA!</b>\n\n"
                f"🅿️ Au apărut <b>+{locuri_noi}</b> loc{'uri' if locuri_noi > 1 else ''} nou{'ă' if locuri_noi > 1 else ''}!\n"
                f"⚡ Intră RAPID și licitează:\n"
                f"🔗 https://parcari-ticketing.primariacraiova.ro"
            )
            if i < 9:
                time.sleep(3)

        # Actualizam baseline ca sa nu re-alertam la aceleasi locuri
        save_baseline(current_count)
        logger.info("Baseline actualizat. 10 alerte trimise.")

        return {
            "statusCode": 200,
            "body": f"SUCCES! Alerte trimise. Locuri noi: +{locuri_noi} (curent={current_count}, vechi={baseline})",
        }

    # ─── NICIO SCHIMBARE ─────────────────────────────────
    logger.info("Nicio schimbare detectata. Urmatoarea verificare in 10 minute.")
    return {
        "statusCode": 200,
        "body": f"Nicio schimbare. Curent: {current_count} = Baseline: {baseline}",
    }
