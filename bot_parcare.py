import os
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- DATELE TALE CONFIGURATE ---
# Token-ul si chat ID-ul se citesc din variabilele de mediu (nu le tinem in cod)
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
URL_SITE = "https://parcari-ticketing.primariacraiova.ro/locparcare"

# XPath-ul exact cerut de tine pentru a incarca pagina cum vrei dupa refresh
XPATH_BUTON_TASTE = "/html[1]/body[1]/div[1]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]/button[1]"

# XPath SUPER-PREcis: Cauta poligoane STRICT in interiorul hartii (leaflet-container)
XPATH_POLIGOANE = "//div[contains(@class, 'leaflet-container')]//*[local-name()='svg']//*[local-name()='path' or local-name()='polygon']"

def trimite_alerta(mesaj):
    """Trimite notificare pe telefon via Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mesaj}
    try: 
        requests.post(url, json=payload, timeout=5)
    except: 
        pass

def porneste_monitorizarea():
    options = webdriver.ChromeOptions()
    options.add_experimental_option("detach", True)
    driver = webdriver.Chrome(options=options)
    driver.get(URL_SITE)
    driver.maximize_window()
    
    print("ETAPA LOGARE: Ai 60 de secunde sa te loghezi si sa pui harta pe zona dorita...")
    time.sleep(60)
    
    # --- STABILIM BAZA ---
    try:
        locuri_initiale = len(driver.find_elements(By.XPATH, XPATH_POLIGOANE))
    except:
        locuri_initiale = 1
        
    if locuri_initiale == 0:
        locuri_initiale = 1 
        
    print(f"BAZA SETATA: Am detectat {locuri_initiale} poligoane pe harta in acest moment.")
    
    # --- INCEPE BUCLA DE REFRESH ---
    while True:
        try:
            print(f"\n[{time.strftime('%H:%M:%S')}] Dau refresh...")
            driver.refresh()
            time.sleep(3) # Asteptam putin sa se incarce structura paginii
            
            # 1. Apasam butonul din meniu
            print(" -> Apas butonul tau...")
            buton = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XPATH_BUTON_TASTE))
            )
            buton.click()
            
            # 2. Asteptam sa se incarce elementele grafice pe harta
            time.sleep(4)
            
            # 3. Numaram din nou poligoanele DOAR de pe harta
            locuri_curente = len(driver.find_elements(By.XPATH, XPATH_POLIGOANE))
            print(f" -> Poligoane detectate acum: {locuri_curente}")
            
            # 4. Verificam matematic daca au aparut elemente noi
            if locuri_curente > locuri_initiale:
                print("SUCCES! AU APARUT LOCURI NOI PE HARTA!")
                
                # Bucla pentru cele 10 mesaje cu pauza de 3 secunde
                for i in range(10):
                    trimite_alerta(f"🚨 [{i+1}/10] ALERTA PARCARE: Au aparut locuri noi! Intra rapid si liciteaza!")
                    time.sleep(3)  # Pauza de 3 secunde intre alerte
                
                # Oprim botul pentru a te lasa sa dai click tu de aici incolo
                break 
            else:
                print(" -> Nicio modificare. Reiau peste 5 secunde...")
                time.sleep(5)
                
        except Exception as e:
            print(" -> Eroare la gasirea elementelor. Reincerc in 5 secunde...")
            time.sleep(5)

if __name__ == "__main__":
    print("Porneste botul radar...")
    trimite_alerta("Radarul a pornit cu succes! Asteapta 60 de secunde pentru configurare.")
    porneste_monitorizarea()