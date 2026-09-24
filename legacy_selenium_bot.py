"""
LEGACY - the first, local version of the bot (Selenium + a visible Chrome window).
Superseded by parking_bot.py and kept for reference only: it no longer works since the
site replaced its Leaflet map with MapLibre (WebGL) in September 2026.
"""
import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- CONFIGURATION ---
# Token and chat ID are read from environment variables (never kept in code)
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SITE_URL = "https://parcari-ticketing.primariacraiova.ro/locparcare"

# Exact XPath of the menu button that reloads the map view after a refresh
XPATH_MENU_BUTTON = "/html[1]/body[1]/div[1]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]/button[1]"

# Polygons strictly inside the map (leaflet-container)
XPATH_POLYGONS = "//div[contains(@class, 'leaflet-container')]//*[local-name()='svg']//*[local-name()='path' or local-name()='polygon']"

def send_alert(message):
    """Sends a phone notification via Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=5)
    except:
        pass

def start_monitoring():
    options = webdriver.ChromeOptions()
    options.add_experimental_option("detach", True)
    driver = webdriver.Chrome(options=options)
    driver.get(SITE_URL)
    driver.maximize_window()

    print("LOGIN STEP: you have 60 seconds to log in and move the map to the area you want...")
    time.sleep(60)

    # --- SET THE BASELINE ---
    try:
        initial_spots = len(driver.find_elements(By.XPATH, XPATH_POLYGONS))
    except:
        initial_spots = 1

    if initial_spots == 0:
        initial_spots = 1

    print(f"BASELINE SET: {initial_spots} polygons on the map right now.")

    # --- REFRESH LOOP ---
    while True:
        try:
            print(f"\n[{time.strftime('%H:%M:%S')}] Refreshing...")
            driver.refresh()
            time.sleep(3) # Give the page structure a moment to load

            # 1. Click the menu button
            print(" -> Clicking the menu button...")
            button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XPATH_MENU_BUTTON))
            )
            button.click()

            # 2. Wait for the map graphics to load
            time.sleep(4)

            # 3. Count the polygons on the map again
            current_spots = len(driver.find_elements(By.XPATH, XPATH_POLYGONS))
            print(f" -> Polygons detected now: {current_spots}")

            # 4. Did new elements appear?
            if current_spots > initial_spots:
                print("SUCCESS! NEW SPOTS APPEARED ON THE MAP!")

                # 10 messages, 3 seconds apart
                for i in range(10):
                    send_alert(f"🚨 [{i+1}/10] PARKING ALERT: New spots appeared! Go bid now!")
                    time.sleep(3)  # 3-second pause between alerts

                # Stop so you can take over from here
                break
            else:
                print(" -> No change. Retrying in 5 seconds...")
                time.sleep(5)

        except Exception as e:
            print(" -> Could not find the elements. Retrying in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    print("Starting the radar bot...")
    send_alert("Radar started! Waiting 60 seconds for setup.")
    start_monitoring()
