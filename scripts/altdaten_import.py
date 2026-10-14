# -*- coding: utf-8 -*-
"""
Altdaten aus der alten KBL-Datenbank (Ordner "Playerdata" vom KBL-Gruender) uebernehmen.

    python scripts/altdaten_import.py                  nur pruefen und berichten (aendert nichts)
    python scripts/altdaten_import.py --schreiben      Datenbank ergaenzen (vorher automatisches Backup)

Erwartet den entpackten Ordner unter  altdaten/Playerdata  im Projektordner
(anderer Ort:  --quelle "C:\\Pfad\\zu\\Playerdata").

Was passiert:
  - Saisons 2020A, 2020B, 2021A, 2021B: Manager, die in der Datenbank fehlen, werden mit
    Liga, Platz, Gesamtpunkten und Spieltagspunkten ergaenzt.
  - Quali-Saison 2019B (5 Gruppen): wird ebenfalls uebernommen und in config/kbl.json als
    "quali" markiert -> auf der Webseite sichtbar, aber ohne Titel und ohne KBL-Score.
  - Zuordnung zu bestehenden Managern: gleicher Name in derselben Saison, sonst gleiche Liga
    und gleiche Gesamtpunkte (umbenannte Manager), sonst die feste Liste ZUORDNUNG unten.
    Wer nicht zugeordnet werden kann, bekommt einen neuen Eintrag mit der alten ID (z. B. "00042").
  - Bestehende Eintraege bleiben unveraendert. Ausnahme: Sind die Spieltagspunkte offensichtlich
    falsch (Summe passt nicht zu den Gesamtpunkten, in der alten Datenbank aber schon),
    werden sie ersetzt.
  - Pokal 2022A: wird aus  altdaten/KBL Cup/KBLCup 2022A/KBLCup_2022A.json  uebernommen,
    falls er noch fehlt.

Danach:  python scripts/kbl_score.py  (bzw. ueber run_me) und  python update.py --nur-webseite
"""
import argparse
import json
import os
import shutil
import sys
from datetime import datetime

SYSTEM = "kbl"
SAISONS = ["2019B", "2020A", "2020B", "2021A", "2021B"]
# Erinnerungs-Saisons: werden angezeigt, zaehlen aber nicht fuer Titel und KBL-Score
QUALI = {"2019B": {"matchday_number": "17", "first_matchday": "1", "last_matchday": "17"}}

# Alte ID -> Kickbase-ID, fuer Manager, die spaeter unter anderem Namen/Account dabei waren.
# None = bewusst NICHT zuordnen (eigener Eintrag), z. B. bei haeufigen Namen.
ZUORDNUNG = {
    # Beispiele (werden im Bericht mit Namen angezeigt):
    # "00031": "1293897",
}
# Haeufige Namen, die NICHT automatisch per Namen einem spaeteren Manager zugeordnet werden
NICHT_PER_NAME = {"jannik", "joshua"}

# Pokal: unbekannte Kickbase-IDs durch die aktuelle ID ersetzen (alter Account -> neuer Account)
POKAL_ID_ERSETZEN = {
    "1042089": "1048029",   # Fabi1893: Zahlendreher bei der Pokal-Anmeldung 2022A
}


def norm(x):
    return (x or "").strip().lower()


def name_reparieren(n):
    """Manche alten Namen sind doppelt kodiert (z. B. 'SalihamidÅ¾iÄ‡' statt 'Salihamidžić')."""
    try:
        r = n.encode("cp1252").decode("utf-8")
        return r if r != n else n
    except (UnicodeEncodeError, UnicodeDecodeError):
        return n


def lade(pfad):
    with open(pfad, encoding="utf-8-sig") as f:
        return json.load(f)


def alte_saison(quelle, s):
    for p in (os.path.join(quelle, "Saison %s" % s, "Database_KBL_%s.json" % s),
              os.path.join(quelle, "Database_KBL_%s.json" % s)):
        if os.path.exists(p):
            return lade(p)
    return None


def aktiv(v):
    return v.get("Liga") and v["Liga"] != "KBL"


def leerer_eintrag(laenge):
    return {"League": None, "Place": None, "Points": None,
            "MdPoints": [0] * laenge, "MdPlace": [0] * laenge}


def spieltage_auffuellen(md, gesamt):
    """Alte DB 2021B kennt nur die ersten Spieltage. Der Rest wird wie in der bestehenden
    Datenbank gleichmaessig verteilt, damit die Gesamtpunkte stimmen."""
    md = list(md)
    if sum(md) >= gesamt:
        return md
    letzte = max([i for i, p in enumerate(md) if p] or [0])
    frei = list(range(letzte + 1, len(md)))
    if not frei:
        return md
    rest = gesamt - sum(md)
    je = rest // len(frei)
    for i in frei:
        md[i] = je
    md[frei[-1]] += rest - je * len(frei)
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quelle", default=os.path.join("altdaten", "Playerdata"))
    ap.add_argument("--pokal", default=os.path.join("altdaten", "KBL Cup", "KBLCup 2022A", "KBLCup_2022A.json"))
    ap.add_argument("--schreiben", action="store_true")
    a = ap.parse_args()

    db_pfad = "league_systems/%s/databases/%s_database.json" % (SYSTEM, SYSTEM)
    if not os.path.exists(db_pfad):
        sys.exit("Datenbank nicht gefunden: %s (Skript im Ordner KBL2.0 starten)" % db_pfad)
    if not os.path.isdir(a.quelle):
        sys.exit("Ordner mit den Altdaten nicht gefunden: %s" % a.quelle)
    db = lade(db_pfad)
    config = lade("config/%s.json" % SYSTEM)
    admin = str(config.get("admin_id"))
    alle_saisons = sorted(set(k for m in db.values() for k in m if k[:2] == "20"))

    alt = {s: alte_saison(a.quelle, s) for s in SAISONS}
    alt = {s: d for s, d in alt.items() if d}
    if not alt:
        sys.exit("Keine alten Saison-Datenbanken (Database_KBL_2020A.json usw.) gefunden.")

    # ---------------- Zuordnung alte ID -> Kickbase-ID ----------------
    zuord, wie = {}, {}
    for s, old in alt.items():
        in_saison = {c: m[s] for c, m in db.items()
                     if c != admin and isinstance(m.get(s), dict) and m[s].get("League")}
        per_name = {norm(db[c].get("Username")): c for c in in_saison}
        belegt = set()
        for k, v in old.items():
            if aktiv(v) and norm(v["Username"]) in per_name and k not in zuord:
                zuord[k] = per_name[norm(v["Username"])]
                wie[k] = "Name"
                belegt.add(zuord[k])
            elif aktiv(v) and k in zuord:
                belegt.add(zuord[k])
        for k, v in old.items():
            if not aktiv(v) or k in zuord:
                continue
            treffer = [c for c in in_saison if c not in belegt and in_saison[c]["League"] == v["Liga"]
                       and in_saison[c]["Points"] == v["Punkte GES"]]
            if len(treffer) == 1:
                zuord[k] = treffer[0]
                wie[k] = "umbenannt (%s: %s -> %s)" % (s, v["Username"].strip(), db[treffer[0]]["Username"].strip())
                belegt.add(treffer[0])

    alte_namen = {}
    for s in sorted(alt):
        for k, v in alt[s].items():
            if aktiv(v):
                alte_namen[k] = name_reparieren(v["Username"].strip())   # spaetester Name gewinnt

    per_name_global = {}
    for c, m in db.items():
        per_name_global.setdefault(norm(m.get("Username")), []).append(c)
    for k, n in alte_namen.items():
        if k in zuord:
            continue
        if k in ZUORDNUNG:
            if ZUORDNUNG[k]:
                zuord[k] = str(ZUORDNUNG[k])
                wie[k] = "feste Zuordnung"
            continue
        kand = per_name_global.get(norm(n), [])
        if len(kand) == 1 and norm(n) not in NICHT_PER_NAME:
            zuord[k] = kand[0]
            wie[k] = "gleicher Name in spaeterer Saison"

    # ---------------- Ergaenzen ----------------
    neu_manager, neu_eintraege, korrigiert, gleich = [], 0, [], 0
    angelegt, importiert = set(), set()
    for s in sorted(alt):
        old = alt[s]
        for k, v in old.items():
            if not aktiv(v):
                continue
            ziel = zuord.get(k)
            if ziel is None:
                ziel = k
                if ziel in db and ziel not in angelegt:
                    ziel = "9" + k   # ID schon von jemand anderem belegt -> ausweichen
                zuord[k] = ziel
                if ziel not in db:
                    angelegt.add(ziel)
                    laenge = 18
                    db[ziel] = {"Username": alte_namen[k], "Info": {"KBL Score": 0, "League": None, "Place": 0}}
                    for x in alle_saisons:
                        db[ziel][x] = leerer_eintrag(laenge)
                    neu_manager.append((ziel, alte_namen[k]))
            m = db[ziel]
            e = m.get(s)
            md_alt = list(v.get("Punkte Spieltag") or [])
            if isinstance(e, dict) and e.get("League"):
                md = e.get("MdPoints") or []
                if md == md_alt or e.get("Points") != v["Punkte GES"]:
                    gleich += 1
                    continue
                if sum(md) != e["Points"] and sum(md_alt) == v["Punkte GES"]:
                    korrigiert.append((s, m["Username"].strip(), md[:4], md_alt[:4]))
                    e["MdPoints"] = md_alt
                else:
                    gleich += 1
                continue
            laenge = len(md_alt) or 18
            m[s] = {"League": v["Liga"], "Place": v["Platz"], "Points": v["Punkte GES"],
                    "MdPoints": spieltage_auffuellen(md_alt, v["Punkte GES"]),
                    "MdPlace": [0] * laenge}
            if v.get("Teamwert"):
                m[s]["TeamValue"] = v["Teamwert"]
            importiert.add((s, ziel))
            neu_eintraege += 1

    # ---------------- Plaetze bereinigen ----------------
    # Die alte Datenbank hat bei Aussteigern den Platz vom Ausstiegstag behalten (doppelte Plaetze).
    # Bestehende Eintraege bleiben fest; die neuen bekommen die freien Plaetze nach Punkten.
    platz_geaendert = []
    for s in sorted(alt):
        ligen = {}
        for c, m in db.items():
            e = m.get(s)
            if c != admin and isinstance(e, dict) and e.get("League"):
                ligen.setdefault(e["League"], []).append(c)
        for liga, ids in ligen.items():
            neu = [c for c in ids if (s, c) in importiert]
            if not neu:
                continue
            fest = set(db[c][s]["Place"] for c in ids if (s, c) not in importiert)
            frei = [p for p in range(1, len(ids) + 1) if p not in fest]
            if len(frei) != len(neu):
                continue
            neu.sort(key=lambda c: (-(db[c][s]["Points"] or 0), db[c][s]["Place"] or 99))
            for c, p in zip(neu, frei):
                if db[c][s]["Place"] != p:
                    platz_geaendert.append((s, liga, db[c]["Username"], db[c][s]["Place"], p))
                    db[c][s]["Place"] = p

    # ---------------- Pokal 2022A ----------------
    pokal_ziel = "league_systems/%s/cup/%sCup_Database_2022A.json" % (SYSTEM, SYSTEM.upper())
    pokal_neu = False
    if os.path.exists(a.pokal) and not os.path.exists(pokal_ziel):
        cup = lade(a.pokal)
        txt = json.dumps(cup)
        for alt_id, neu_id in POKAL_ID_ERSETZEN.items():
            txt = txt.replace('"%s"' % alt_id, '"%s"' % neu_id)
        cup = json.loads(txt)
        ids = set()
        for r in cup.values():
            for mu in r.get("Matchups", []):
                ids.update(str(x) for x in mu)
        ids.discard("Freilos")
        unbekannt = sorted(i for i in ids if i not in db)
        pokal_neu = True

    # ---------------- Bericht ----------------
    print("Altdaten-Abgleich %s\n" % SYSTEM.upper())
    for s in sorted(alt):
        n_alt = sum(1 for v in alt[s].values() if aktiv(v))
        n_db = sum(1 for c, m in db.items() if c != admin and isinstance(m.get(s), dict) and m[s].get("League"))
        print("  %s: %d Manager in der alten Datenbank, danach %d in deiner Datenbank%s"
              % (s, n_alt, n_db, "  (Quali, ohne Wertung)" if s in QUALI else ""))
    print("\nZuordnungen, die nicht ueber den gleichen Namen in derselben Saison liefen:")
    for k, w in sorted(wie.items(), key=lambda x: alte_namen.get(x[0], "")):
        if w != "Name":
            ziel = zuord[k]
            print("  %-20s (alt %s) -> %s (%s)  [%s]" % (alte_namen.get(k), k, db[ziel]["Username"].strip(), ziel, w))
    print("\nNeue Manager (bisher nicht in der Datenbank): %d" % len(neu_manager))
    for i, n in sorted(neu_manager, key=lambda x: x[1].lower()):
        print("  %-20s ID %s" % (n, i))
    print("\nNeue Saison-Eintraege: %d, unveraendert: %d" % (neu_eintraege, gleich))
    if korrigiert:
        print("Korrigierte Spieltagspunkte:")
        for s, n, vorher, nachher in korrigiert:
            print("  %s %s: vorher %s ... jetzt %s ..." % (s, n, vorher, nachher))
    if platz_geaendert:
        print("\nPlaetze angepasst (Aussteiger hatten in der alten Datenbank den Platz vom Ausstiegstag):")
        for s, liga, n, vorher, nachher in platz_geaendert:
            print("  %s %s: %s  Platz %s -> %s" % (s, liga, n.strip(), vorher, nachher))
    if pokal_neu:
        print("\nPokal 2022A wird uebernommen (%d Teilnehmer)." % len(ids))
        if unbekannt:
            print("  Nicht in der Datenbank (erscheinen auf der Seite als 'ID ...'): %s" % ", ".join(unbekannt))
    elif os.path.exists(pokal_ziel):
        print("\nPokal 2022A ist schon vorhanden.")

    if not a.schreiben:
        print("\nNur geprueft, nichts geaendert. Zum Uebernehmen:  python scripts/altdaten_import.py --schreiben")
        return

    stempel = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Quali-Saisons in der Config eintragen bzw. markieren
    cfg_pfad = "config/%s.json" % SYSTEM
    cfg_neu = False
    for qs, werte in QUALI.items():
        if qs not in alt:
            continue
        eintrag = next((x for x in config["seasons"] if x.get("name") == qs), None)
        if eintrag is None:
            eintrag = dict({"name": qs}, **werte)
            eintrag["leagues"] = [{}]
            config["seasons"].append(eintrag)
            cfg_neu = True
        if not eintrag.get("quali"):
            eintrag["quali"] = True
            cfg_neu = True
    if cfg_neu:
        shutil.copy(cfg_pfad, cfg_pfad.replace(".json", "_backup_%s.json" % stempel))
        with open(cfg_pfad, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        print("Config ergaenzt: Saison %s als Qualifikation (ohne Wertung)." % ", ".join(sorted(QUALI)))
    backup = db_pfad.replace(".json", "_backup_%s.json" % stempel)
    shutil.copy(db_pfad, backup)
    with open(db_pfad, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=4)
    if pokal_neu:
        with open(pokal_ziel, "w", encoding="utf-8") as f:
            json.dump(cup, f, indent=4)
    print("\nGespeichert. Backup der alten Datenbank: %s" % backup)
    print("Jetzt den KBL-Score neu berechnen und die Webseite bauen.")


if __name__ == "__main__":
    main()
