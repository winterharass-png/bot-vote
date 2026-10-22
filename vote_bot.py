
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
"""
Bot de vote Hyleria.fr/vote (version téléphone / GitHub Actions) - avec diagnostic
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
RETRY_APRES = 300  # secondes : pas de nouvel essai sur un bouton avant 5 min
dernier_essai = {}
diag_fait = False


def log(msg):
    print(f"[{datetime.now():%d/%m %H:%M:%S}] {msg}", flush=True)


def hote(url):
    return urlparse(url).netloc or url


def diag(page, quand):
    """Indices pour savoir si la page nous voit connecté (sans rien divulguer)."""
    try:
        corps = page.inner_text("body")
    except Exception:
        corps = ""
    log(
        f"[diag {quand}] site={hote(page.url)} "
        f"| pseudo_visible={PSEUDO.lower() in corps.lower()} "
        f"| mot_connexion={bool(re.search(r'se connecter|connexion', corps, re.I))} "
        f"| mot_deconnexion={bool(re.search(r'déconnexion|deconnexion|se déconnecter', corps, re.I))}"
    )


def charger_session():
    brut = os.environ.get("SESSION_JSON")
    if brut:
        with open(SESSION, "w", encoding="utf-8") as f:
            f.write(brut)
    if not os.path.exists(SESSION):
        raise SystemExit("Aucune session : ajoute le secret SESSION_JSON ou session.json")
    with open(SESSION, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):  # export Cookie-Editor -> format Playwright
        cookies = []
        for c in data:
            same = {"no_restriction": "None", "lax": "Lax", "strict": "Strict"}.get(
                c.get("sameSite"), "Lax")
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
        log(f"Session chargée : {len(cookies)} cookies, domaines = "
            f"{sorted({c['domain'] for c in cookies})}")
    return data


def etat(page, nom):
    """Retourne (bouton, compte_a_rebours). bouton=None si introuvable,
    compte_a_rebours='' si le bouton est disponible."""
    btn = page.locator("a, button, div").filter(
        has_text=re.compile(nom.replace("-", r"[-\s]?"), re.I)
    ).last
    if not btn.count():
        return None, None
    m = COUNTDOWN.search(btn.inner_text())
    return btn, (m.group() if m else "")


def cliquer(ctx, page, btn):
    """Imite le geste manuel : clic -> site de vote -> retour -> attente."""
    try:
        with ctx.expect_page(timeout=4000) as nouvelle:
            btn.click()
        ext = nouvelle.value
        try:
            ext.wait_for_load_state("load", timeout=15000)
        except PWTimeout:
            pass
        log(f"  onglet externe ouvert : {hote(ext.url)}")
        ext.wait_for_timeout(6000)
        ext.close()
        page.bring_to_front()
    except PWTimeout:
        # pas de nouvel onglet : le site s'ouvre dans le même onglet
        page.wait_for_timeout(6000)
        log(f"  même onglet, site : {hote(page.url)}")
        if "hyleria.fr" not in page.url:
            page.go_back()
    page.wait_for_timeout(8000)  # le vote est compté après ~5 s sur la page


def voter(browser, state):
    """Retourne le nombre de boutons trouvés."""
    global diag_fait
    ctx = browser.new_context(storage_state=state)
    page = ctx.new_page()
    trouves = 0
    try:
        page.goto(URL, wait_until="networkidle")
        if not diag_fait:
            diag(page, "debut")
            diag_fait = True

        champ = page.locator("input[type='text']").first
        if champ.count() and champ.is_visible():
            champ.fill(PSEUDO)

        for nom in BOUTONS:
            btn, timer = etat(page, nom)
            if btn is None:
                log(f"{nom} : bouton introuvable")
                continue
            trouves += 1
            if timer:
                log(f"{nom} : en attente ({timer})")
                continue
            if time.time() - dernier_essai.get(nom, 0) < RETRY_APRES:
                log(f"{nom} : disponible mais essai récent, j'attends")
                continue

            dernier_essai[nom] = time.time()
            log(f"{nom} : disponible, je vote...")
            cliquer(ctx, page, btn)
            page.goto(URL, wait_until="networkidle")
            _, timer = etat(page, nom)
            if timer:
                log(f"{nom} : VOTE OK, compte à rebours lancé ({timer})")
            else:
                log(f"{nom} : VOTE NON PRIS EN COMPTE (pas de compte à rebours)")
                diag(page, "apres-echec")
    finally:
        ctx.close()
    return trouves


if __name__ == "__main__":
    state = charger_session()
    fin = time.time() + LOOP_MINUTES * 60 if LOOP_MINUTES else None
    echecs = 0
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        while True:
            try:
                echecs = 0 if voter(browser, state) else echecs + 1
            except Exception as e:
                log(f"Erreur : {e}")
                echecs += 1
            if echecs >= 5:
                raise SystemExit("Boutons introuvables 5 fois de suite : session expirée ?")
            if fin and time.time() > fin:
                break
            time.sleep(CHECK_EVERY)
