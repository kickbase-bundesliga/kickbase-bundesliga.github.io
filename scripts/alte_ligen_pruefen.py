# -*- coding: utf-8 -*-
"""
Alte Kickbase-Ligen pruefen (nur lesen, nichts aendern)
=======================================================

Idee: Ligen, die nach dem Umzug auf den Admin-Account nicht mehr weitergespielt
wurden, stehen evtl. noch auf dem Endstand ihrer letzten Saison.

Aufruf (im Ordner KBL2.0):

    1) Welche Ligen sieht ein Account ueberhaupt?
       python scripts/alte_ligen_pruefen.py --zugang config/privat.txt

    2) Bestimmte League-IDs abfragen:
       python scripts/alte_ligen_pruefen.py --zugang config/privat.txt 1234567 2345678

    3) Viele IDs: eine pro Zeile in altdaten/alte_liga_ids.txt eintragen, dann
       python scripts/alte_ligen_pruefen.py --zugang config/privat.txt --datei altdaten/alte_liga_ids.txt

--zugang: Textdatei wie config/kbl.txt (Zeile 1 E-Mail, Zeile 2 Passwort).
          Ohne Angabe wird config/kbl.txt (KBL-Admin) benutzt.
          Fuer den alten privaten Account z. B. config/privat.txt anlegen -
          diese Datei NIE weitergeben.

Ergebnis: api_dump/alte_ligen/<ID>/*.json (ohne Zugangsdaten)
          Bitte den Ordner api_dump/alte_ligen als ZIP schicken.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_erkunden import Api, ligen_finden, listen_mit_ids, name_von, speichern  # noqa: E402

ZIEL = os.path.join("api_dump", "alte_ligen")


def lese_zugang(pfad):
    if not os.path.exists(pfad):
        sys.exit("Nicht gefunden: %s" % pfad)
    with open(pfad, encoding="utf-8-sig") as f:
        z = [x.strip() for x in f.read().splitlines() if x.strip()]
    return z[0], z[1]


def punkte(e):
    for k in ("sp", "tp", "p", "pt"):
        if isinstance(e.get(k), (int, float)):
            return e[k]
    return "?"


def kurz(api, lid):
    ordner = os.path.join(ZIEL, str(lid))
    anfragen = {
        "overview": "/v4/leagues/%s/overview?includeManagersAndBattles=true" % lid,
        "me": "/v4/leagues/%s/me" % lid,
        "settings": "/v4/leagues/%s/settings" % lid,
        "ranking": "/v4/leagues/%s/ranking" % lid,
        "ranking_tag34": "/v4/leagues/%s/ranking?dayNumber=34" % lid,
        "ranking_tag17": "/v4/leagues/%s/ranking?dayNumber=17" % lid,
        "ranking_tag15": "/v4/leagues/%s/ranking?dayNumber=15" % lid,
    }
    ergebnis = {}
    for name, pfad in anfragen.items():
        d = api.get(pfad)
        speichern(ordner, name, d)
        ergebnis[name] = d
    ov = ergebnis["overview"]
    lname = ov.get("lnm") or ov.get("n") or ov.get("name") or "?"
    print("\n=== Liga %s  (%s)" % (lid, lname))
    for name in ("ranking", "ranking_tag34", "ranking_tag17", "ranking_tag15"):
        d = ergebnis[name]
        if "_fehler" in d:
            print("  %-14s Fehler %s %s" % (name, d["_fehler"], d.get("_text", "")[:120]))
            continue
        listen = list(listen_mit_ids(d))
        if not listen:
            print("  %-14s keine Managerliste (Felder: %s)" % (name, ", ".join(list(d)[:12])))
            continue
        l = listen[0]
        top = ", ".join("%s %s" % (name_von(e), punkte(e)) for e in l[:3])
        print("  %-14s %2d Manager | Top: %s" % (name, len(l), top))
        if name == "ranking":
            print("  %-14s Felder je Manager: %s" % ("", ", ".join(sorted(l[0]))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ids", nargs="*")
    ap.add_argument("--zugang", default=os.path.join("config", "kbl.txt"))
    ap.add_argument("--datei")
    a = ap.parse_args()

    email, pw = lese_zugang(a.zugang)
    api = Api(email, pw)
    print("Login ok.")

    ids = list(a.ids)
    if a.datei:
        with open(a.datei, encoding="utf-8-sig") as f:
            ids += [z.strip().split()[0] for z in f if z.strip() and not z.startswith("#")]

    sel, ligen = ligen_finden(api)
    speichern(ZIEL, "_ligen_dieses_accounts", sel)
    print("\nLigen, in denen dieser Account Mitglied ist: %d" % len(ligen))
    for lid, n in ligen:
        print("  %-10s %s" % (lid, n))

    if not ids:
        print("\nKeine IDs angegeben - nur die Liste oben. Zum Abfragen IDs anhaengen (siehe Kopf der Datei).")
        return
    for lid in ids:
        kurz(api, lid)
    print("\nFertig. Rohdaten in %s - bitte diesen Ordner als ZIP schicken." % ZIEL)


if __name__ == "__main__":
    main()
