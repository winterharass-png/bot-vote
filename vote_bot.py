
"""
Bot Hyleria - diagnostic de session et vérification des votes.
"""

import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

URL = "https://hyleria.fr/vote"
PSEUDO = "WinterHarass"
BOUTONS = ["SERVEURLISTE", "SERVEUR-MINECRAFT-VOTE"]

CHECK_EVERY = int(os.environ.get("CHECK_EVERY", "60"))
LOOP_MINUTES = int(os.environ.get("LOOP_MINUTES", "0"))
SESSION = "session.json"
COUNTDOWN = re.compile(r"\d{2}:\d{2}:\d{2}")


def log(msg):
    print(f"[{datetime.now():%d/%m %H:%M:%S}] {msg}", flush=True)


def hote(url):
    return urlparse(url).netloc or url


def charger_session():
    brut = os.environ.get("SESSION_JSON")

    if brut:
        with open(SESSION, "w", encoding="utf-8") as f:
            f.write(brut)

    if not os.path.exists(SESSION):
        raise SystemExit(
            "Session absente : configure le secret SESSION_JSON."
        )

    with open(SESSION, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        cookies = []

        for c in data:
            same = {
                "no_restriction": "None",
                "lax": "Lax",
                "strict": "Strict",
            }.get(str(c.get("sameSite", "")).lower(), "Lax")

            cookie = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "httpOnly": bool(c.get("httpOnly")),
                "secure": bool(c.get("secure")) or same == "None",
                "sameSite": same,
            }

            if c.get("expirationDate") and not c.get("session"):
                cookie["expires"] = c["expirationDate"]

            cookies.append(cookie)

        data = {"cookies": cookies, "origins": []}
        log(f"Session chargée : {len(cookies)} cookies")

    return data


def diagnostic(page, moment):
    try:
        corps = page.locator("body").inner_text(timeout=5000)
    except Exception:
        corps = ""

    log(
        f"[Diagnostic {moment}] site={hote(page.url)} "
        f"| pseudo_visible={'WinterHarass' in corps}"
    )


def charger_page(page):
    response = page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(3000)

    if response:
        log(f"Page chargée : HTTP {response.status}")

    return response


def trouver_bouton(page, nom):
    elements = page.locator("a, button").filter(
        has_text=re.compile(re.escape(nom), re.I)
    )

    for i in range(elements.count()):
        element = elements.nth(i)

        try:
            if element.is_visible():
                return element
        except Exception:
            continue

    return None


def verifier_site(browser, state):
    ctx = browser.new_context(storage_state=state)
    page = ctx.new_page()

    try:
        charger_page(page)
        diagnostic(page, "initial")

        champ = page.locator("input[type='text']").first

        if champ.count() and champ.is_visible():
            champ.fill(PSEUDO)

        for nom in BOUTONS:
            btn = trouver_bouton(page, nom)

            if btn is None:
                log(f"{nom} : bouton introuvable")
                continue

            try:
                texte = btn.inner_text(timeout=5000)
            except Exception:
                texte = ""

            timer = COUNTDOWN.search(texte)

            if timer:
                log(f"{nom} : prochain vote dans {timer.group()}")
            else:
                log(
                    f"{nom} : aucun compte à rebours détecté. "
                    "Disponibilité du vote non confirmée."
                )

        log("Vérification terminée.")

    finally:
        ctx.close()


if __name__ == "__main__":
    state = charger_session()
    fin = time.time() + LOOP_MINUTES * 60 if LOOP_MINUTES else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        try:
            while True:
                try:
                    verifier_site(browser, state)
                except Exception as e:
                    log(f"Erreur : {type(e).__name__}: {e}")

                if fin and time.time() >= fin:
                    break

                time.sleep(CHECK_EVERY)

        finally:
            browser.close()
            
