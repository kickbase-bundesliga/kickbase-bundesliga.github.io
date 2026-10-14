# -*- coding: utf-8 -*-
"""
Vergleicht die Spieltags-Extras mit der Datenbank (aktuelle Tabellen).

    python scripts/extras_pruefen.py kbl
    python scripts/extras_pruefen.py kwbl

Zeigt pro Liga, wie viele Manager in der Datenbank stehen und wie viele beim
letzten Abruf der Extras gefunden wurden, und nennt die Abweichungen mit Namen.
Liest nur lokale Dateien, keine API-Abfragen.
"""
import json
import os
import sys

sys.path.append("./")
from scripts import utils


def main(system):
    config = utils.read_json("config/%s" % system)
    admin = str(config.get("admin_id"))
    season = utils.get_current_season(system)["name"]
    db = utils.read_json("league_systems/%s/databases/%s_database" % (system, system))
    pfad = os.path.join("league_systems", system, "extras", "%s.json" % season)
    if not os.path.exists(pfad):
        sys.exit("Keine Extras fuer Saison %s gefunden (%s)." % (season, pfad))
    with open(pfad, encoding="utf8") as f:
        extras = json.load(f)
    if not extras.get("md"):
        sys.exit("Die Extras-Datei enthaelt noch keine Spieltage.")
    md = max(extras["md"], key=int)
    gefunden = extras["md"][md]["managers"]

    # Datenbank: wer steht in dieser Saison in welcher Liga
    in_db = {}
    for mid, m in db.items():
        if str(mid) == admin:
            continue
        d = m.get(season)
        if isinstance(d, dict) and d.get("League"):
            in_db[str(mid)] = (d["League"], (m.get("Username") or "?").strip())

    ligen = sorted(set([v[0] for v in in_db.values()] + [v["l"] for v in gefunden.values()]))
    print("Saison %s, Vergleich mit Spieltag %s der Extras\n" % (season, md))
    print("%-22s %10s %10s" % ("Liga", "Datenbank", "Extras"))
    print("-" * 44)
    summe_db = summe_ex = 0
    abweichungen = []
    for liga in ligen:
        db_ids = set(i for i, v in in_db.items() if v[0] == liga)
        ex_ids = set(i for i, v in gefunden.items() if v["l"] == liga)
        summe_db += len(db_ids)
        summe_ex += len(ex_ids)
        markierung = "" if db_ids == ex_ids else "  <-- abweichend"
        print("%-22s %10d %10d%s" % (liga, len(db_ids), len(ex_ids), markierung))
        for i in sorted(db_ids - ex_ids):
            abweichungen.append("%s: %s (ID %s) steht in der Datenbank, wurde bei Kickbase aber nicht gefunden"
                                % (liga, in_db[i][1], i))
        for i in sorted(ex_ids - db_ids):
            name = in_db[i][1] if i in in_db else "?"
            wo = (" - laut Datenbank in %s" % in_db[i][0]) if i in in_db else " - nicht in der Datenbank"
            abweichungen.append("%s: %s (ID %s) bei Kickbase gefunden%s" % (liga, name, i, wo))
    print("-" * 44)
    print("%-22s %10d %10d\n" % ("Gesamt", summe_db, summe_ex))
    if abweichungen:
        print("Abweichungen:")
        for a in abweichungen:
            print("  - " + a)
    else:
        print("Keine Abweichungen - Datenbank und Extras stimmen ueberein.")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1].lower() not in ("kbl", "kwbl"):
        sys.exit("Aufruf: python scripts/extras_pruefen.py kbl")
    main(sys.argv[1].lower())
