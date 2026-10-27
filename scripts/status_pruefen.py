# -*- coding: utf-8 -*-
"""
Abo-Status der Manager pruefen (nur lesen)
==========================================

Holt fuer alle Manager aller Ligen des Accounts das Manager-Dashboard und zaehlt,
welche Werte das Feld "st" (und weitere Kandidaten) annehmen. Bekannte Faelle
(z. B. Admin = Amateur, Poeti = Member) zeigen dann, welcher Wert was bedeutet.

    python scripts/status_pruefen.py kbl
    python scripts/status_pruefen.py kbl --bekannt 1487878=Member

--bekannt  ID=Status, mehrfach moeglich (der Admin-Account wird automatisch als Amateur gefuehrt)

Dauer: ca. 0,5 Sekunden je Manager (bei 400 Managern gut 3 Minuten).
Ergebnis: api_dump/status/status.csv und zusammenfassung.txt  - bitte beides schicken.
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_erkunden import Api, zugangsdaten, ligen_finden  # noqa: E402

ZIEL = os.path.join("api_dump", "status")
FELDER = ("st", "t", "nd", "adm", "pl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("system", choices=["kbl", "kwbl"])
    ap.add_argument("--bekannt", action="append", default=[])
    a = ap.parse_args()
    os.makedirs(ZIEL, exist_ok=True)

    api = Api(*zugangsdaten(a.system))
    admin = str((api.login_antwort.get("u") or {}).get("id"))
    bekannt = {admin: "Amateur (Admin)"}
    for b in a.bekannt:
        if "=" in b:
            k, v = b.split("=", 1)
            bekannt[k.strip()] = v.strip()
    _, ligen = ligen_finden(api)
    print("Login ok, %d Ligen. Das dauert ein paar Minuten ..." % len(ligen))

    zeilen, gesehen = [], set()
    for lid, lname in ligen:
        r = api.get("/v4/leagues/%s/ranking" % lid)
        for u in (r.get("us") or []) if isinstance(r, dict) else []:
            uid = str(u.get("i"))
            if uid in gesehen and uid not in bekannt:
                continue
            gesehen.add(uid)
            d = api.get("/v4/leagues/%s/managers/%s/dashboard" % (lid, uid))
            if not isinstance(d, dict) or "_fehler" in d:
                continue
            z = {"liga": lname, "id": uid, "name": d.get("unm"), "bekannt": bekannt.get(uid, "")}
            for f in FELDER:
                z[f] = d.get(f)
            z["ranking_felder"] = json.dumps({k: v for k, v in u.items() if k in ("iapl", "pa", "hll", "adm")})
            zeilen.append(z)
        print("  %-20s fertig (%d Manager bisher)" % (lname, len(zeilen)))

    with open(os.path.join(ZIEL, "status.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(zeilen[0]), delimiter=";")
        w.writeheader()
        w.writerows(zeilen)

    out = []
    for f in FELDER + ("ranking_felder",):
        zaehler = {}
        for z in zeilen:
            zaehler[json.dumps(z[f])] = zaehler.get(json.dumps(z[f]), 0) + 1
        if len(zaehler) <= 8:
            out.append("%-15s %s" % (f, ", ".join("%s: %d" % kv for kv in sorted(zaehler.items()))))
    out.append("\nBekannte Accounts:")
    for z in zeilen:
        if z["bekannt"]:
            out.append("  %-20s %-10s %-18s st=%s t=%s" % (z["name"], z["id"], z["bekannt"], z["st"], z["t"]))
    text = "\n".join(out)
    with open(os.path.join(ZIEL, "zusammenfassung.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print("\n" + text)
    print("\nFertig. Bitte den Ordner %s als ZIP schicken." % ZIEL)


if __name__ == "__main__":
    main()
