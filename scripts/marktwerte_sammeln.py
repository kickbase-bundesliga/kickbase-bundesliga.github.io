# -*- coding: utf-8 -*-
"""
Spieler-Marktwerte sammeln (einmal am Tag)
==========================================

Holt fuer Bundesliga, 2. Bundesliga, La Liga und Frauen-Bundesliga die aktuellen
Marktwerte aller Spieler und legt je Liga und Tag eine kleine CSV-Datei ab:

    marktwerte/<liga>/<JJJJ-MM-TT>.csv     (Spieler-ID;Spieler;Verein;Vereinsname;Position;Marktwert)

Abgefragt wird nur der Kader je Verein (teamprofile liefert alle Spieler mit Marktwert
in einer Antwort): rund 70 Abfragen am Tag, kein Abruf je Spieler.
Die Webseite (Reiter "Spieler-Marktwerte") rechnet daraus die Differenzen zu
1, 3, 7 und 14 Tagen vorher - die gibt es also erst ab dem ersten Abholtag.

    python scripts/marktwerte_sammeln.py            heutigen Stand holen (falls noch nicht da)
    python scripts/marktwerte_sammeln.py --neu      heutigen Stand neu holen und ueberschreiben

Online laeuft das taeglich ueber den Workflow "Spieler-Marktwerte" (Login wie KBL).
Nur lesende API-Abfragen. Python 3.7, nur Standardbibliothek.
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASIS = "https://api.kickbase.com/v4"
PAUSE = 0.25

ORDNER = "marktwerte"
# Kickbase-Wettbewerb, Ordnername, Anzeigename
LIGEN = [
    (1, "bundesliga", "Bundesliga"),
    (2, "2-bundesliga", "2. Bundesliga"),
    (3, "la-liga", "La Liga"),
    (4, "frauen-bundesliga", "Frauen-Bundesliga"),
]
KOPF = ["Spieler-ID", "Spieler", "Verein", "Vereinsname", "Position", "Marktwert"]


def zugangsdaten():
    """Wie scripts/utils.zugangsdaten: online aus den Secrets KBL_EMAIL/KBL_PASSWORT,
    lokal aus config/kbl.txt (Zeile 1 E-Mail, Zeile 2 Passwort)."""
    email = os.environ.get("KBL_EMAIL", "").strip()
    passwort = os.environ.get("KBL_PASSWORT", "").strip()
    if email and passwort:
        return email, passwort
    pfad = os.path.join("config", "kbl.txt")
    if not os.path.exists(pfad):
        sys.exit("Keine Zugangsdaten: Secrets KBL_EMAIL/KBL_PASSWORT oder Datei config/kbl.txt fehlen.")
    with open(pfad, encoding="utf-8-sig") as f:
        zeilen = [z.strip() for z in f.read().splitlines() if z.strip()]
    return zeilen[0], zeilen[1]


class Api:
    """Eigenstaendig (nur Standardbibliothek), damit der Workflow keine Pakete braucht."""

    def __init__(self):
        email, passwort = zugangsdaten()
        self.token, self.anfragen = None, 0
        antwort = self._anfrage("POST", "/user/login", {"em": email, "pass": passwort, "loy": False, "rep": {}})
        self.token = antwort.get("tkn") if isinstance(antwort, dict) else None
        if not self.token:
            fehler = antwort.get("_fehler") if isinstance(antwort, dict) else antwort
            sys.exit("Login fehlgeschlagen (%s)" % fehler)

    def _anfrage(self, methode, pfad, body=None, versuche=3):
        daten = json.dumps(body).encode("utf-8") if body is not None else None
        for versuch in range(versuche):
            req = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            if daten is not None:
                req.add_header("Content-Type", "application/json")
            if self.token:
                req.add_header("Authorization", "Bearer " + self.token)
            self.anfragen += 1
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    text = r.read().decode("utf-8")
                time.sleep(PAUSE)
                return json.loads(text) if text else {}
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and versuch < versuche - 1:
                    time.sleep(3 * (versuch + 1))
                    continue
                return {"_fehler": e.code}
            except Exception as e:
                if versuch < versuche - 1:
                    time.sleep(3)
                    continue
                return {"_fehler": str(e)}
        return {"_fehler": "unbekannt"}

    def get(self, pfad):
        return self._anfrage("GET", pfad)


def heute_berlin():
    """Datum in Deutschland (ohne Zeitzonen-Bibliothek: Sommerzeit grob Ende Maerz bis Ende Oktober)."""
    jetzt = datetime.now(timezone.utc)
    sommer = 4 <= jetzt.month <= 9 or (jetzt.month == 3 and jetzt.day >= 25) or (jetzt.month == 10 and jetzt.day < 25)
    return (jetzt + timedelta(hours=2 if sommer else 1)).strftime("%Y-%m-%d")


def spieler_listen(obj):
    """Sucht in einer Antwort Listen von Spielern (Objekte mit 'i' und Name/Position)."""
    if isinstance(obj, list):
        if obj and all(isinstance(x, dict) and "i" in x and ("n" in x or "ln" in x or "pos" in x) for x in obj):
            yield obj
        for x in obj:
            for t in spieler_listen(x):
                yield t
    elif isinstance(obj, dict):
        for v in obj.values():
            for t in spieler_listen(v):
                yield t


def vereine(api, wettbewerb):
    """Vereine des Wettbewerbs aus dem Spielplan: {tid: Kuerzel}."""
    d = api.get("/competitions/%d/matchdays" % wettbewerb)
    out = {}
    for tag in d.get("it", []) if isinstance(d, dict) else []:
        for m in tag.get("it", []):
            for t, sy in (("t1", "t1sy"), ("t2", "t2sy")):
                if m.get(t):
                    out[str(m[t])] = m.get(sy) or str(m[t])
    return out


def liga_holen(api, wettbewerb):
    teams = vereine(api, wettbewerb)
    zeilen, fehlend = {}, []
    for tid in sorted(teams, key=lambda x: int(x) if x.isdigit() else 0):
        d = api.get("/competitions/%d/teams/%s/teamprofile" % (wettbewerb, tid))
        listen = list(spieler_listen(d)) if isinstance(d, dict) and "_fehler" not in d else []
        if not listen:
            fehlend.append(teams[tid])
            continue
        vereinsname = d.get("tn") or ""
        for s in listen[0]:
            if s.get("mv") is None:
                continue
            name = s.get("n") or s.get("ln") or str(s["i"])
            if s.get("fn") and s.get("ln"):
                name = "%s %s" % (s["fn"], s["ln"])
            zeilen[str(s["i"])] = [str(s["i"]), name, teams[tid], vereinsname, s.get("pos") or "", int(s["mv"])]
    return teams, zeilen, fehlend


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--neu", action="store_true", help="heutigen Stand neu holen und ueberschreiben")
    a = ap.parse_args()

    datum = heute_berlin()
    offen = [l for l in LIGEN if a.neu or not os.path.exists(os.path.join(ORDNER, l[1], datum + ".csv"))]
    if not offen:
        print("Marktwerte vom %s sind schon fuer alle Ligen da." % datum)
        return

    api = Api()
    fehler = 0
    for wettbewerb, ordner, name in offen:
        teams, zeilen, fehlend = liga_holen(api, wettbewerb)
        if not teams or len(fehlend) > len(teams) / 2:
            print("❌ %-18s nicht gespeichert: %d von %d Vereinen nicht abrufbar" % (name, len(fehlend), len(teams)))
            fehler += 1
            continue
        os.makedirs(os.path.join(ORDNER, ordner), exist_ok=True)
        pfad = os.path.join(ORDNER, ordner, datum + ".csv")
        with open(pfad + ".tmp", "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(KOPF)
            w.writerows(sorted(zeilen.values(), key=lambda z: -z[5]))
        os.replace(pfad + ".tmp", pfad)
        hinweis = " (fehlend: %s)" % ", ".join(fehlend) if fehlend else ""
        print("✅ %-18s %3d Spieler aus %d Vereinen%s" % (name, len(zeilen), len(teams) - len(fehlend), hinweis))
    print("Stand %s, %d API-Anfragen." % (datum, api.anfragen))
    if fehler == len(offen):
        sys.exit(1)


if __name__ == "__main__":
    main()
