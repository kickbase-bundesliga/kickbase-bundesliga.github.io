"""
Einmalig ausfuehren: uebernimmt bereits vorhandene Admin-Korrekturen in die Datenbank.

Die Datenbank enthaelt schon die echten Gesamtpunkte laut Kickbase ("Points") und die
Spieltagspunkte ("MdPoints"). Die Differenz ist die Admin-Korrektur. Dieses Script
speichert sie als "Corrections" (zugeordnet zum angegebenen Spieltag) und berechnet
danach die Platzierungen pro Spieltag ("MdPlace") und den aktuellen Platz ("Place")
inkl. Korrekturen neu (der Platz aus dem Kickbase-Dashboard enthaelt sie nicht).

Aufruf (im Projektordner):
    python scripts/migrate_corrections.py kbl 2026B 1
    python scripts/migrate_corrections.py kwbl 2026B 1
Der letzte Wert ist der KBL-Spieltag, dem die Korrektur zugeordnet wird
(in 2026B betrafen die Gutschriften den 1. Spieltag).
"""
import sys
sys.path.append("./")
from scripts import utils


def migrate(system, season_name, matchday_kbl):
    filename = f"league_systems/{system}/databases/{system}_database"
    database = utils.read_json(filename)

    last_filled = 0
    changed = 0
    for manager_id, mdata in database.items():
        sdata = mdata.get(season_name)
        if not isinstance(sdata, dict) or not sdata.get("League"):
            continue
        md = sdata.get("MdPoints") or []
        filled = [i for i, p in enumerate(md) if p]
        if filled:
            last_filled = max(last_filled, filled[-1])
        points = sdata.get("Points")
        if not points:
            continue
        delta = utils.record_correction(sdata, matchday_kbl, points - sum(p or 0 for p in md))
        if delta:
            changed += 1
            print(f"✏️  {mdata.get('Username')} ({sdata['League']}): {delta:+d} Punkte")

    # Platzierungen je Spieltag neu berechnen
    leagues = {}
    for manager_id, mdata in database.items():
        sdata = mdata.get(season_name)
        if isinstance(sdata, dict) and sdata.get("League"):
            leagues.setdefault(sdata["League"], []).append(sdata)
    for league, members in leagues.items():
        for md in range(1, last_filled + 1):
            ranked = sorted(members, key=lambda s: utils.total_points_upto(s, md), reverse=True)
            for rank, sdata in enumerate(ranked, start=1):
                if md < len(sdata["MdPlace"]):
                    sdata["MdPlace"][md] = rank
                if md == last_filled:
                    sdata["Place"] = rank   # Kickbase-Platz (pl) enthaelt keine Korrekturen

    for manager_id, mdata in database.items():
        sdata = mdata.get(season_name)
        if isinstance(sdata, dict) and sdata.get("League") and sdata.get("Place"):
            mdata.setdefault("Info", {})["Place"] = sdata["Place"]

    utils.write_json(filename, database, True)
    print(f"✅ {changed} Korrekturen uebernommen, Platzierungen fuer Spieltag 1-{last_filled} neu berechnet.")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    migrate(sys.argv[1].lower(), sys.argv[2], int(sys.argv[3]))
