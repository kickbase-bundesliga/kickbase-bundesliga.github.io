# -*- coding: utf-8 -*-
"""
Prueft, ob die Spieltagspunkte aus der Kickbase-Historie der Manager zu deiner Datenbank passen,
und listet auf, was sich in Altsaisons ergaenzen liesse.

    python scripts/historie_pruefen.py kbl          Historie holen (bzw. Zwischenspeicher nutzen) und pruefen
    python scripts/historie_pruefen.py kbl --neu    Historie neu von Kickbase holen

Schreibt NICHTS in die Datenbank. Ergebnis:
  - Ausgabe im Fenster: Uebereinstimmung je Saison + Beispiele fuer Abweichungen
  - historie_ergaenzungen.csv im Projektordner: welche Manager in welchen Saisons fehlen
    oder unvollstaendig sind und von Kickbase Spieltagspunkte haetten (fuer Excel)
Die Rohdaten liegen in league_systems/<system>/historie/<Manager-ID>.json.
"""
import csv
import json
import os
import sys

sys.path.append("./")
from scripts import utils
from scripts.spieltag_extras import Api, ligen_des_systems


# ---------------------------------------------------------------- Saison-Zuordnung

def saison_zuordnung(config):
    """KBL-Saisons aus der Config: Name -> (erster, letzter Bundesliga-Spieltag)."""
    out = {}
    for s in config.get("seasons", []):
        try:
            out[s["name"]] = (int(s["first_matchday"]), int(s["last_matchday"]))
        except (KeyError, ValueError, TypeError):
            pass
    return out


def kbl_saison(sn, day, saisons):
    """Kickbase-Saison '2020/2021' + Bundesliga-Spieltag -> (KBL-Saison, KBL-Spieltag).
    B = Hinrunde (Saisonstart im Jahr Y1), A = Rueckrunde (Jahr Y2)."""
    try:
        y1, y2 = sn.split("/")
        y1, y2 = y1.strip(), y2.strip()
        if len(y2) == 2:
            y2 = y1[:2] + y2
    except ValueError:
        return None, None
    for name in (y1 + "B", y2 + "A"):
        if name in saisons:
            erster, letzter = saisons[name]
            if erster <= day <= letzter:
                return name, day - erster + 1
    # Saison nicht in der Config: Standardaufteilung 1-17 / 18-34
    if day <= 17:
        return y1 + "B", day
    return y2 + "A", day - 17


# ---------------------------------------------------------------- Abruf

def manager_aller_ligen(api, ligen, admin):
    manager = {}
    for lid, lname in ligen:
        r = api.get("/leagues/%s/ranking" % lid)
        for u in (r.get("us") or []) if isinstance(r, dict) else []:
            uid = str(u.get("i"))
            if uid != admin:
                manager[uid] = (lid, lname, u.get("n") or uid)
    return manager


def historie_holen(api, manager, ordner, neu):
    os.makedirs(ordner, exist_ok=True)
    geholt = 0
    for i, (uid, (lid, lname, name)) in enumerate(sorted(manager.items(), key=lambda x: x[1][1])):
        pfad = os.path.join(ordner, uid + ".json")
        if os.path.exists(pfad) and not neu:
            continue
        d = api.get("/leagues/%s/managers/%s/performance" % (lid, uid))
        if isinstance(d, dict) and "_fehler" not in d:
            with open(pfad, "w", encoding="utf8") as f:
                json.dump(d, f, ensure_ascii=False)
            geholt += 1
        if (i + 1) % 50 == 0:
            print("   %d von %d Managern ..." % (i + 1, len(manager)))
    return geholt


def historie_lesen(pfad, saisons):
    """-> {KBL-Saison: {KBL-Spieltag: Punkte}}"""
    with open(pfad, encoding="utf8") as f:
        d = json.load(f)
    out = {}
    for s in d.get("it", []):
        sn = s.get("sn") or ""
        for t in s.get("it", []):
            if t.get("cur"):
                continue  # laufender Spieltag
            name, md = kbl_saison(sn, int(t.get("day") or 0), saisons)
            if name:
                out.setdefault(name, {})[md] = t.get("mdp") or 0
    return out


# ---------------------------------------------------------------- Auswertung

def main(system, neu=False):
    config = utils.read_json("config/%s" % system)
    admin = str(config.get("admin_id"))
    aktuell = utils.get_current_season(system)["name"]
    saisons = saison_zuordnung(config)
    db = utils.read_json("league_systems/%s/databases/%s_database" % (system, system))
    ordner = os.path.join("league_systems", system, "historie")

    print("Login ...")
    api = Api(system)
    ligen = ligen_des_systems(api, system, config)
    print("   %d Ligen" % len(ligen))
    manager = manager_aller_ligen(api, ligen, admin)
    print("   %d Manager" % len(manager))
    geholt = historie_holen(api, manager, ordner, neu)
    print("   %d Historien neu geholt, %d API-Anfragen\n" % (geholt, api.anfragen))

    vergleich = {}      # Saison -> [gleich, abweichend]
    beispiele = []
    ergaenzungen = []
    for uid, (lid, lname, name) in sorted(manager.items(), key=lambda x: x[1][2].lower()):
        pfad = os.path.join(ordner, uid + ".json")
        if not os.path.exists(pfad):
            continue
        hist = historie_lesen(pfad, saisons)
        m = db.get(uid, {})
        for saison, tage in sorted(hist.items()):
            if saison == aktuell or not tage:
                continue
            d = m.get(saison) if isinstance(m.get(saison), dict) else None
            md_db = (d or {}).get("MdPoints") or []
            gefuellt = 0
            for md, p in tage.items():
                wert_db = md_db[md] if md < len(md_db) else None
                if wert_db:
                    gefuellt += 1
                    v = vergleich.setdefault(saison, [0, 0])
                    if wert_db == p:
                        v[0] += 1
                    else:
                        v[1] += 1
                        if len(beispiele) < 15:
                            beispiele.append("%s %s Spieltag %d: Datenbank %s, Kickbase %s"
                                             % (saison, name, md, wert_db, p))
            fehlend = len([1 for p in tage.values() if p]) - gefuellt
            if fehlend > 0:
                ergaenzungen.append({
                    "Saison": saison, "Manager": name, "ID": uid, "Aktuelle Liga": lname,
                    "In Datenbank": ("ja, Liga " + d["League"]) if d and d.get("League") else "nein",
                    "Spieltage bei Kickbase": len(tage),
                    "davon fehlen in Datenbank": fehlend,
                    "Summe Punkte Kickbase": sum(tage.values()),
                })

    print("Uebereinstimmung mit der Datenbank (nur Spieltage, die in beiden vorhanden sind):\n")
    print("%-8s %10s %10s %10s %8s" % ("Saison", "Vergleiche", "gleich", "abweichend", "Quote"))
    print("-" * 50)
    for s in sorted(vergleich):
        g, a = vergleich[s]
        print("%-8s %10d %10d %10d %7.1f%%" % (s, g + a, g, a, 100.0 * g / (g + a)))
    if not vergleich:
        print("(keine ueberlappenden Spieltage gefunden)")
    if beispiele:
        print("\nBeispiele fuer Abweichungen:")
        for b in beispiele:
            print("  - " + b)

    ziel = "historie_ergaenzungen.csv"
    with open(ziel, "w", encoding="utf-8-sig", newline="") as f:
        felder = ["Saison", "Manager", "ID", "Aktuelle Liga", "In Datenbank",
                  "Spieltage bei Kickbase", "davon fehlen in Datenbank", "Summe Punkte Kickbase"]
        w = csv.DictWriter(f, fieldnames=felder, delimiter=";")
        w.writeheader()
        for e in sorted(ergaenzungen, key=lambda e: (e["Saison"], e["Manager"].lower())):
            w.writerow(e)

    print("\nMoegliche Ergaenzungen je Saison (Manager mit Kickbase-Punkten, die in der Datenbank fehlen):")
    je_saison = {}
    for e in ergaenzungen:
        je_saison.setdefault(e["Saison"], []).append(e)
    for s in sorted(je_saison):
        neu_ganz = sum(1 for e in je_saison[s] if e["In Datenbank"] == "nein")
        print("  %s: %d Manager (%d ganz neu, %d unvollstaendig)"
              % (s, len(je_saison[s]), neu_ganz, len(je_saison[s]) - neu_ganz))
    print("\nDetails fuer Excel: %s" % ziel)


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    if not args or args[0] not in ("kbl", "kwbl"):
        sys.exit("Aufruf: python scripts/historie_pruefen.py kbl   [--neu]")
    main(args[0], neu="--neu" in args)
