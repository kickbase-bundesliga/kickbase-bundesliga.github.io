# -*- coding: utf-8 -*-
"""
Findet die Kickbase-Wettbewerbsnummer eines Ligasystems (nur lesende Abfragen).

    python scripts/wettbewerb_suchen.py kwbl

1. Sucht in den Ligadaten des Admin-Accounts nach Feldern wie cpi / competitionId.
2. Probiert die Wettbewerbe 1-20 durch und zeigt Anzahl Spieltage und ersten Spieltermin.
   Frauen-Bundesliga: 14 Teams -> 26 Spieltage.
Rohdaten landen in api_dump/wettbewerb/.
"""
import json
import os
import sys

sys.path.append("./")
from scripts import utils  # noqa: E402
from scripts.spieltag_extras import Api  # noqa: E402

SCHLUESSEL = ("cpi", "cid", "competitionId", "competition", "cp")


def treffer(obj, pfad=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SCHLUESSEL and not isinstance(v, (dict, list)):
                yield pfad + "/" + k, v
            yield from treffer(v, pfad + "/" + k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            yield from treffer(v, "%s[%d]" % (pfad, i))


def speichern(name, daten):
    os.makedirs(os.path.join("api_dump", "wettbewerb"), exist_ok=True)
    with open(os.path.join("api_dump", "wettbewerb", name + ".json"), "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)


def main():
    if len(sys.argv) < 2:
        sys.exit("Aufruf: python scripts/wettbewerb_suchen.py kwbl")
    system = sys.argv[1].lower()
    import automatik
    config = utils.read_json("config/" + system)
    namen = set(n for lc in config["leagues"] for n in lc["names"])
    api = Api(system)
    speichern("login", {k: v for k, v in api.login_antwort.items() if k != "tkn"})

    print("1) Ligadaten durchsuchen")
    gefunden = list(treffer(api.login_antwort, "login"))
    liga_id = None
    for obj in api.login_antwort.get("srvl", []) if isinstance(api.login_antwort.get("srvl"), list) else []:
        if obj.get("n") in namen:
            liga_id = obj.get("i") or obj.get("id")
            break
    if liga_id:
        for name, pfad in [("me", "/leagues/%s/me" % liga_id), ("settings", "/leagues/%s/settings" % liga_id),
                           ("overview", "/leagues/%s/overview" % liga_id)]:
            d = api.get(pfad)
            speichern(name, d)
            gefunden += list(treffer(d, name))
    for pfad, wert in gefunden:
        print("   %-40s %s" % (pfad, wert))
    if not gefunden:
        print("   nichts gefunden")

    print("\n2) Wettbewerbe 1-20 durchprobieren")
    for nr in range(1, 21):
        d = api.get("/competitions/%d/matchdays" % nr)
        plan = automatik.spielplan_lesen(d)
        if not plan:
            continue
        erster = plan[min(plan)][0]
        print("   Wettbewerb %2d: %2d Spieltage, erster Termin %s" % (nr, len(plan), automatik.berlin(erster)))
        speichern("wettbewerb_%d" % nr, d)
    print("\nFertig. Schick mir die Ausgabe.")


if __name__ == "__main__":
    main()
