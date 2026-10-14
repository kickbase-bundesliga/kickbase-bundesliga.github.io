# -*- coding: utf-8 -*-
"""
Abschlusstabellen (nur Endstand, keine Spieltage) in die Datenbank uebernehmen,
z. B. aus Screenshots von Facebook oder aus den alten Bildern.

    python scripts/tabellen_import.py                 nur pruefen und berichten (aendert nichts)
    python scripts/tabellen_import.py --schreiben     Datenbank ergaenzen (vorher automatisches Backup)

Quelle: altdaten/abschlusstabellen.csv  (Trennzeichen ;  -  in Excel bearbeitbar)
    Saison;Liga;Platz;Name;Punkte;ID;Quelle
    2021B;KBL - Liga 4A;1;Daveray;16622;;KBL4A_Final_2021B.png

Spalte ID ist optional: leer = automatische Zuordnung ueber den Namen.
Eine Kickbase-ID (oder eine bestehende ID aus der Datenbank) dort eintragen, um einen
Manager fest zuzuordnen, "neu", um ihn bewusst als eigenen Manager anzulegen, oder einen
Verweis wie "@2021A 4A 3" (= derselbe Manager wie 2021A Liga 4A Platz 3).

Zuordnung ohne ID:
  - genau ein Manager mit diesem Namen in der Datenbank, der in dieser Saison noch
    keinen Eintrag hat  -> wird ihm zugeordnet
  - mehrere moegliche Manager -> wird als eigener (neuer) Manager angelegt und im Bericht
    unter "Mehrdeutig" aufgefuehrt; dann bei Bedarf die ID in der CSV eintragen
  - kein Manager mit dem Namen -> neuer Manager. Gleicher Name in mehreren Saisons der CSV
    = dieselbe Person (ausser zwei Eintraege in derselben Saison).
Bestehende Saison-Eintraege werden nie ueberschrieben.
"""
import argparse
import csv
import json
import os
import shutil
import sys
from datetime import datetime

SYSTEM = "kbl"


def norm(x):
    return (x or "").strip().lower()


def lade(pfad):
    with open(pfad, encoding="utf-8-sig") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quelle", default=os.path.join("altdaten", "abschlusstabellen.csv"))
    ap.add_argument("--schreiben", action="store_true")
    a = ap.parse_args()

    db_pfad = "league_systems/%s/databases/%s_database.json" % (SYSTEM, SYSTEM)
    if not os.path.exists(db_pfad):
        sys.exit("Datenbank nicht gefunden (Skript im Ordner KBL2.0 starten).")
    if not os.path.exists(a.quelle):
        sys.exit("CSV nicht gefunden: %s" % a.quelle)
    db = lade(db_pfad)
    config = lade("config/%s.json" % SYSTEM)
    admin = str(config.get("admin_id"))
    saison_len = {s["name"]: int(s.get("matchday_number") or 17) for s in config["seasons"]}
    alle_saisons = sorted(set(k for m in db.values() for k in m if k[:2] == "20"))

    with open(a.quelle, encoding="utf-8-sig", newline="") as f:
        zeilen = [z for z in csv.DictReader(f, delimiter=";") if (z.get("Name") or "").strip()]

    def hat_saison(mid, s):
        e = db.get(mid, {}).get(s)
        return isinstance(e, dict) and bool(e.get("League"))

    per_name = {}
    vorhanden = set()      # (Saison, Liga, Punkte, Platz) -> schon in der Datenbank (z. B. zweiter Lauf)
    for mid, m in db.items():
        if mid != admin:
            per_name.setdefault(norm(m.get("Username")), []).append(mid)
            for k, e in m.items():
                if k[:2] == "20" and isinstance(e, dict) and e.get("League"):
                    vorhanden.add((k, e["League"], e.get("Points"), e.get("Place")))
    schon = 0

    neue_ids = (9000 + i for i in range(1, 100000))
    gruppe = {}            # Name -> neue ID (gleicher Name = gleiche Person, saisonweise)
    belegt = {}            # (ID, Saison) -> Liga, auch fuer Eintraege aus dieser CSV
    plan, mehrdeutig, per_name_zu, neu_angelegt, uebersprungen = [], {}, {}, {}, []

    def verweis(text):
        try:
            vs, vl, vp = text[1:].split()
            vp = int(vp)
        except ValueError:
            return None
        for ziel_, s_, liga_, platz_, *_ in plan:          # in diesem Lauf neu angelegt
            if s_ == vs and liga_.endswith(" " + vl) and platz_ == vp:
                return ziel_
        for mid, m in db.items():                          # schon in der Datenbank
            e = m.get(vs)
            if isinstance(e, dict) and (e.get("League") or "").endswith(" " + vl) and e.get("Place") == vp:
                return mid
        return None

    for z in zeilen:
        s, liga, name = z["Saison"].strip(), z["Liga"].strip(), z["Name"].strip()
        try:
            platz, punkte = int(z["Platz"]), int(str(z["Punkte"]).replace(".", ""))
        except ValueError:
            uebersprungen.append((s, liga, name, "Platz/Punkte nicht lesbar"))
            continue
        if (s, liga, punkte, platz) in vorhanden:
            schon += 1
            continue
        fest = (z.get("ID") or "").strip()
        ziel = None
        if fest.startswith("@"):
            # Verweis auf einen anderen Tabellenplatz, z. B. "@2021A 4A 3" = wer 2021A in Liga 4A Platz 3 war
            ziel = verweis(fest)
            if ziel is None:
                uebersprungen.append((s, liga, name, "Verweis %s nicht gefunden" % fest))
                continue
        elif fest and fest.lower() != "neu":
            ziel = fest
        elif not fest:
            alle = per_name.get(norm(name), [])
            if len(alle) == 1:
                c = alle[0]
                if not hat_saison(c, s) and (c, s) not in belegt:
                    ziel = c
                    per_name_zu.setdefault(name, (ziel, db[ziel]["Username"].strip()))
                # sonst: der bekannte Manager spielte in dieser Saison woanders -> andere Person
            elif len(alle) > 1:
                mehrdeutig.setdefault(name, set()).update(alle)
        if ziel is None:
            ziel = gruppe.get(norm(name))
            if ziel is None or (ziel, s) in belegt or hat_saison(ziel, s):
                ziel = "0%d" % next(neue_ids)
                while ziel in db:
                    ziel = "0%d" % next(neue_ids)
                gruppe[norm(name)] = ziel
            neu_angelegt.setdefault(ziel, name)
        if hat_saison(ziel, s):
            uebersprungen.append((s, liga, name, "hat in %s schon einen Eintrag (%s)" % (s, db[ziel][s]["League"])))
            continue
        if (ziel, s) in belegt:
            uebersprungen.append((s, liga, name, "steht in %s schon in %s" % (s, belegt[(ziel, s)])))
            continue
        belegt[(ziel, s)] = liga
        plan.append((ziel, s, liga, platz, punkte, name))

    # ---------------- Bericht ----------------
    print("Abschlusstabellen: %d Zeilen gelesen, %d werden uebernommen, %d sind schon in der Datenbank\n"
          % (len(zeilen), len(plan), schon))
    je = {}
    for ziel, s, liga, *_ in plan:
        je.setdefault((s, liga), 0)
        je[(s, liga)] += 1
    for (s, liga), n in sorted(je.items()):
        print("  %s %-16s %2d Manager" % (s, liga, n))
    print("\nPer Namen zugeordnet (bitte kurz ueberfliegen):")
    for name, (mid, uname) in sorted(per_name_zu.items(), key=lambda x: x[0].lower()):
        print("  %-24s -> %s (%s)" % (name, uname, mid))
    if mehrdeutig:
        print("\nMehrdeutig - als eigener Manager angelegt. Falls es einer dieser Manager ist, ID in die CSV eintragen:")
        for name, ids in sorted(mehrdeutig.items(), key=lambda x: x[0].lower()):
            opts = []
            for mid in sorted(ids):
                ss = sorted(k for k in db[mid] if k[:2] == "20" and hat_saison(mid, k))
                opts.append("%s (ab %s)" % (mid, ss[0] if ss else "?"))
            print("  %-24s %s" % (name, ", ".join(opts)))
    nur_neu = {i: n for i, n in neu_angelegt.items() if n not in mehrdeutig}
    print("\nNeue Manager ohne Treffer in der Datenbank: %d" % len(nur_neu))
    print("  " + ", ".join(sorted(nur_neu.values(), key=str.lower)))
    if uebersprungen:
        print("\nNicht uebernommen:")
        for s, liga, name, grund in uebersprungen:
            print("  %s %s %s: %s" % (s, liga, name, grund))

    if not a.schreiben:
        print("\nNur geprueft, nichts geaendert. Zum Uebernehmen:  python scripts/tabellen_import.py --schreiben")
        return

    for ziel, s, liga, platz, punkte, name in plan:
        if ziel not in db:
            db[ziel] = {"Username": name, "Info": {"KBL Score": 0, "League": None, "Place": 0}}
            for x in alle_saisons:
                db[ziel][x] = {"League": None, "Place": None, "Points": None,
                               "MdPoints": [0] * 18, "MdPlace": [0] * 18}
        laenge = saison_len.get(s, 17) + 1
        db[ziel][s] = {"League": liga, "Place": platz, "Points": punkte,
                       "MdPoints": [0] * laenge, "MdPlace": [0] * laenge, "FinalOnly": True}
    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = db_pfad.replace(".json", "_backup_%s.json" % stempel)
    shutil.copy(db_pfad, backup)
    with open(db_pfad, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4)
    print("\nGespeichert. Backup: %s" % backup)
    print("Danach: KBL-Score neu berechnen und  python update.py --nur-webseite")


if __name__ == "__main__":
    main()
