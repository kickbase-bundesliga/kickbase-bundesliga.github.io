# -*- coding: utf-8 -*-
"""
API-Erkundung fuer KBL 2.0
==========================

Fragt die Kickbase-API (v4) fuer eine Liga ab und speichert jede Antwort roh
als JSON, damit wir sehen, welche Daten pro Manager wirklich verfuegbar sind.
Am Ende entsteht eine lesbare Feld-Uebersicht (uebersicht.txt).

Es wird nur gelesen (GET), nichts veraendert.

Aufruf (im Projektordner KBL2.0):

    1) Ligen anzeigen:
       python scripts/api_erkunden.py kbl

    2) Eine Liga komplett abfragen (alle Manager):
       python scripts/api_erkunden.py kbl --liga "Liga 1"

    3) Nur ein Manager, bestimmter Spieltag:
       python scripts/api_erkunden.py kbl --liga "Liga 1" --manager Alienrobben --spieltag 6

--liga darf eine Liga-ID oder ein Teil des Liganamens sein.
Ergebnis landet in:  api_dump/<system>/<liga>/

Laeuft mit Python 3.7, nur Standardbibliothek.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASIS = "https://api.kickbase.com"
PAUSE = 0.4          # Sekunden zwischen zwei Anfragen (API schonen)
COMPETITION = 1      # 1 = Bundesliga


# ---------------------------------------------------------------- API-Zugriff

class Api:
    def __init__(self, email, passwort):
        self.token = None
        antwort = self._anfrage("POST", "/v4/user/login",
                                {"em": email, "pass": passwort,
                                 "loy": False, "rep": {}})
        self.token = antwort.get("tkn")
        if not self.token:
            print("Login fehlgeschlagen. Antwort der API:")
            print(json.dumps(antwort, ensure_ascii=False)[:800])
            print("Verwendete E-Mail: %r" % email)
            sys.exit(1)
        self.login_antwort = antwort

    def _anfrage(self, methode, pfad, body=None):
        daten = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
        if daten is not None:
            req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                text = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return {"_fehler": e.code, "_text": e.read().decode("utf-8", "replace")[:500]}
        except Exception as e:  # Netzwerkproblem o. ae.
            return {"_fehler": str(e)}
        finally:
            time.sleep(PAUSE)
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return {"_fehler": "keine JSON-Antwort", "_text": text[:500]}

    def get(self, pfad):
        return self._anfrage("GET", pfad)


# ---------------------------------------------------------------- Hilfen

def zugangsdaten(system):
    # Zugangsdaten aus config/<system>.txt oder aus GitHub Secrets (siehe utils.zugangsdaten)
    sys.path.insert(0, os.path.abspath("."))
    from scripts import utils
    email, passwort, _ = utils.zugangsdaten(system)
    return email, passwort


def dateiname(text):
    return re.sub(r"[^\w\-]+", "_", str(text)).strip("_")[:60] or "x"


def speichern(ordner, name, daten):
    os.makedirs(ordner, exist_ok=True)
    with open(os.path.join(ordner, name + ".json"), "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)


def listen_mit_ids(obj):
    """Sucht alle Listen von Objekten, die ein Feld 'i' (ID) haben."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) and "i" in x for x in obj):
            yield obj
        for x in obj:
            for t in listen_mit_ids(x):
                yield t
    elif isinstance(obj, dict):
        for v in obj.values():
            for t in listen_mit_ids(v):
                yield t


def name_von(eintrag):
    for k in ("n", "un", "unm", "name"):
        if isinstance(eintrag.get(k), str):
            return eintrag[k]
    return str(eintrag.get("i"))


def ligen_finden(api):
    sel = api.get("/v4/leagues/selection")
    ligen = []
    for liste in listen_mit_ids(sel):
        for l in liste:
            ligen.append((str(l["i"]), name_von(l)))
        break
    return sel, ligen


def manager_finden(ranking):
    for liste in listen_mit_ids(ranking):
        return [(str(m["i"]), name_von(m)) for m in liste]
    return []


def spieler_ids(squad):
    """Spieler-IDs aus dem Kader (Feld 'pi', zur Sicherheit auch 'i')."""
    for s in squad.get("it", []) if isinstance(squad, dict) else []:
        if isinstance(s, dict) and (s.get("pi") or s.get("i")):
            return [str(s.get("pi") or s.get("i"))]
    return []


# ---------------------------------------------------------------- Uebersicht

def beschreiben(obj, einzug="", tiefe=0, zeilen=None):
    """Feldstruktur mit Beispielwerten - Listen werden nur am 1. Eintrag gezeigt."""
    if zeilen is None:
        zeilen = []
    if tiefe > 6:
        return zeilen
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                art = "Liste[%d]" % len(v) if isinstance(v, list) else "Objekt"
                zeilen.append("%s%s: %s" % (einzug, k, art))
                beschreiben(v, einzug + "    ", tiefe + 1, zeilen)
            else:
                wert = json.dumps(v, ensure_ascii=False)
                if len(wert) > 60:
                    wert = wert[:57] + "..."
                zeilen.append("%s%s = %s" % (einzug, k, wert))
    elif isinstance(obj, list) and obj:
        if not isinstance(obj[0], (dict, list)):
            # Liste einfacher Werte (z. B. Spieler-IDs): die ersten Werte zeigen
            zeilen.append(einzug + "Werte: " + json.dumps(obj[:12], ensure_ascii=False)[:200])
        elif all(isinstance(x, dict) and "t" in x for x in obj):
            # Listen mit Typ-Feld (z. B. Aktivitaets-Feed): ein Beispiel je Typ
            gesehen = set()
            for x in obj:
                if x["t"] in gesehen:
                    continue
                gesehen.add(x["t"])
                zeilen.append("%s[Beispiel fuer t = %s]" % (einzug, x["t"]))
                beschreiben(x, einzug + "    ", tiefe + 1, zeilen)
        else:
            zeilen.append(einzug + "[erster Eintrag]")
            beschreiben(obj[0], einzug + "    ", tiefe + 1, zeilen)
    return zeilen


def uebersicht_schreiben(ordner):
    ausgabe = []
    for wurzel, _, dateien in sorted(os.walk(ordner)):
        for d in sorted(dateien):
            if not d.endswith(".json"):
                continue
            pfad = os.path.join(wurzel, d)
            with open(pfad, encoding="utf-8") as f:
                daten = json.load(f)
            ausgabe.append("=" * 70)
            ausgabe.append(os.path.relpath(pfad, ordner))
            ausgabe.append("=" * 70)
            ausgabe.extend(beschreiben(daten) or ["(leer)"])
            ausgabe.append("")
    ziel = os.path.join(ordner, "uebersicht.txt")
    with open(ziel, "w", encoding="utf-8") as f:
        f.write("\n".join(ausgabe))
    return ziel


# ---------------------------------------------------------------- Ablauf

def main():
    p = argparse.ArgumentParser(description="Kickbase-API erkunden (nur lesen)")
    p.add_argument("system", choices=["kbl", "kwbl"])
    p.add_argument("--liga", help="Liga-ID oder Teil des Liganamens")
    p.add_argument("--manager", help="nur diesen Manager (Teil des Namens)")
    p.add_argument("--spieltag", type=int, help="Spieltag fuers Team Center (Standard: aktueller)")
    args = p.parse_args()

    email, pw = zugangsdaten(args.system)
    print("Login ...")
    api = Api(email, pw)

    sel, ligen = ligen_finden(api)
    basis = os.path.join("api_dump", args.system)
    speichern(basis, "ligen_auswahl", sel)

    if not args.liga:
        print("\nLigen dieses Accounts:")
        for lid, name in ligen:
            print("  %-10s %s" % (lid, name))
        print("\nWeiter mit:  python scripts/api_erkunden.py %s --liga \"<Name oder ID>\"" % args.system)
        return

    treffer = [l for l in ligen if l[0] == args.liga or args.liga.lower() in l[1].lower()]
    if not treffer:
        sys.exit("Keine Liga passt zu: " + args.liga)
    if len(treffer) > 1:
        print("Mehrere Ligen passen, nehme die erste: " + ", ".join(n for _, n in treffer))
    lid, lname = treffer[0]
    ordner = os.path.join(basis, dateiname(lname))
    tag = "?dayNumber=%d" % args.spieltag if args.spieltag else ""
    print("Liga: %s (%s)" % (lname, lid))

    # --- Liga-weite Daten
    liga = {
        "ranking": "/v4/leagues/%s/ranking%s" % (lid, tag),
        "overview": "/v4/leagues/%s/overview?includeManagersAndBattles=true" % lid,
        "settings": "/v4/leagues/%s/settings" % lid,
        "settings_managers_admin": "/v4/leagues/%s/settings/managers" % lid,
        "aktivitaeten_feed": "/v4/leagues/%s/activitiesFeed?start=0&max=100" % lid,
        "transfermarkt": "/v4/leagues/%s/market" % lid,
        "spieltage_bundesliga": "/v4/competitions/%d/matchdays" % COMPETITION,
    }
    ergebnisse = {}
    for name, pfad in liga.items():
        print("  Liga: " + name)
        ergebnisse[name] = api.get(pfad)
        speichern(os.path.join(ordner, "_liga"), name, ergebnisse[name])

    manager = manager_finden(ergebnisse["ranking"]) or manager_finden(ergebnisse["overview"])
    if args.manager:
        manager = [m for m in manager if args.manager.lower() in m[1].lower()]
    if not manager:
        print("Keine Manager gefunden - bitte _liga/ranking.json pruefen.")
    print("  %d Manager" % len(manager))

    # --- Pro Manager
    erster_spieler = None
    for uid, uname in manager:
        print("  Manager: " + uname)
        mordner = os.path.join(ordner, dateiname(uname))
        abfragen = {
            "dashboard": "/v4/leagues/%s/managers/%s/dashboard" % (lid, uid),
            "performance": "/v4/leagues/%s/managers/%s/performance" % (lid, uid),
            "kader_squad": "/v4/leagues/%s/managers/%s/squad" % (lid, uid),
            "transfers": "/v4/leagues/%s/managers/%s/transfer?start=0" % (lid, uid),
            "teamcenter_aufstellung": "/v4/leagues/%s/users/%s/teamcenter%s" % (lid, uid, tag),
        }
        for name, pfad in abfragen.items():
            daten = api.get(pfad)
            speichern(mordner, name, daten)
            if name == "kader_squad" and erster_spieler is None:
                ids = spieler_ids(daten)
                erster_spieler = ids[0] if ids else None

    # --- Ein Beispielspieler (zeigt, was es pro Spieler gibt)
    if erster_spieler:
        print("  Beispielspieler: " + erster_spieler)
        sordner = os.path.join(ordner, "_beispielspieler")
        for name, pfad in {
            "spieler": "/v4/leagues/%s/players/%s" % (lid, erster_spieler),
            "transfer_historie": "/v4/leagues/%s/players/%s/transferHistory?start=0" % (lid, erster_spieler),
            "transfers": "/v4/leagues/%s/players/%s/transfers" % (lid, erster_spieler),
            "performance": "/v4/leagues/%s/players/%s/performance" % (lid, erster_spieler),
            "marktwert_92_tage": "/v4/leagues/%s/players/%s/marketvalue/92" % (lid, erster_spieler),
        }.items():
            speichern(sordner, name, api.get(pfad))

    ziel = uebersicht_schreiben(ordner)
    print("\nFertig. Rohdaten:  " + ordner)
    print("Feld-Uebersicht:   " + ziel)
    print("Schick mir gern die uebersicht.txt (oder einen Ausschnitt), dann planen wir Top-Elf und Transferpreise.")


if __name__ == "__main__":
    main()
