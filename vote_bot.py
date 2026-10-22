```python
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
RETRY_APRES = 300
dernier_essai = {}
diag_fait = False


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
            "Aucune session : ajoute le secret SESSION_JSON ou session.json"
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

        log(
            f"Session chargée : {len(cookies)} cookies, "
            f"domaines = {sorted({c['domain'] for c in cookies})}"
        )

    return data


def diag(page, quand):
    """Diagnostic de connexion sans afficher les cookies."""
    try:
        corps = page.locator("body").inner_text(timeout=5000)
    except Exception:
        corps = ""

    log(
        f"[diag {quand}] site={hote(page.url)} "
        f"| pseudo_visible={'WinterHarass'.lower() in corps.lower()} "
        f"| mot_connexion={bool(re.search(r'se connecter|connexion', corps, re.I))} "
        f"| mot_deconnexion={bool(re.search(r'déconnexion|deconnexion|se déconnecter', corps, re.I))}"
    )


def charger_page(page):
    """Charge la page sans attendre networkidle."""
    response = page.goto(
        URL,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    page.wait_for_timeout(3000)

    if response:
        log(f"Page chargée : HTTP {response.status}")

    return response


def etat(page, nom):
    """
    Retourne (bouton, compte_a_rebours).
    Le compte à rebours est vide si aucun timer n'est détecté.
    """
    btn = page.locator("a, button, div").filter(
        has_text=re.compile(nom.replace("-", r"[-\s]?"), re.I)
    ).last

    if not btn.count():
        return None, None

    try:
        texte = btn.inner_text(timeout=5000)
    except Exception:
        return None, None

    match = COUNTDOWN.search(texte)
    return btn, (match.group() if match else "")


def cliquer(ctx, page, btn):
    """Détecte l'ouverture éventuelle d'un nouvel onglet."""
    try:
        with ctx.expect_page(timeout=4000) as nouvelle:
            btn.click(timeout=10000)

        ext = nouvelle.value

        try:
            ext.wait_for_load_state("domcontentloaded", timeout=15000)
        except PWTimeout:
            pass

        log(f"Onglet externe ouvert : {hote(ext.url)}")
        ext.wait_for_timeout(6000)
        ext.close()

        page.bring_to_front()

    except PWTimeout:
        log("Aucun nouvel onglet détecté.")

        page.wait_for_timeout(6000)

        log(f"Page actuelle : {hote(page.url)}")

        if "hyleria.fr" not in page.url:
            try:
                page.go_back(
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                page.wait_for_timeout(3000)
            except PWTimeout:
                log("Le retour a dépassé le délai autorisé.")

    page.wait_for_timeout(8000)


def voter(browser, state):
    """Vérifie les boutons et effectue les vérifications disponibles."""
    global diag_fait

    ctx = browser.new_context(storage_state=state)
    page = ctx.new_page()
    trouves = 0

    try:
        charger_page(page)

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
                log(f"{nom} : essai récent, nouvelle vérification plus tard")
                continue

            dernier_essai[nom] = time.time()
            log(f"{nom} : bouton disponible")

            # Le clic est effectué uniquement si le bouton est visible.
            if not btn.is_visible():
                log(f"{nom} : bouton non visible, clic ignoré")
                continue

            cliquer(ctx, page, btn)

            charger_page(page)

            _, timer = etat(page, nom)

            if timer:
                log(f"{nom} : compte à rebours détecté ({timer})")
            else:
                log(
                    f"{nom} : aucun compte à rebours détecté. "
                    "Vote non confirmé."
                )
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

        try:
            while True:
                try:
                    nombre = voter(browser, state)
                    echecs = 0 if nombre else echecs + 1

                except Exception as e:
                    log(f"Erreur : {type(e).__name__}: {e}")
                    echecs += 1

                if echecs >= 5:
                    raise SystemExit(
                        "5 échecs consécutifs : vérifie la session "
                        "et la disponibilité du site."
                    )

                if fin and time.time() > fin:
                    break

                time.sleep(CHECK_EVERY)

        finally:
            browser.close()
```
