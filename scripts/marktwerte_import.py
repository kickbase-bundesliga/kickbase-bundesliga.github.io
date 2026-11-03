# -*- coding: utf-8 -*-
"""
Alte Marktwerte aus Excel-Spielerlisten nachtragen (marktwerte/<liga>/<JJJJ-MM-TT>.csv)
=====================================================================================

Die Spielerlisten (Spielerliste_<Nr>.xlsx, je Liga ein Blatt: Vorname, Nachname, Mannschaft,
Position, Marktwert, Marktwertveraenderung, ...) haben keine Spieler-ID und kein Datum.

    python scripts/marktwerte_import.py Spielerliste_*.xlsx --erste 56=2026-10-21 [--pruefen] [--ueberschreiben]

  --erste NR=DATUM   Datum der Liste mit dieser Nummer; die anderen folgen tageweise (Nr+1 = Tag+1).
  --pruefen          nur anzeigen, nichts schreiben
  --ueberschreiben   vorhandene Tagesdateien ersetzen (sonst werden sie uebersprungen)

Zuordnung der Spieler-ID ueber die naechste vorhandene Tagesdatei nach den Listen (gleicher
Verein + Name, bei Gleichnamigen Position und Marktwert). Geprueft wird auch die Tageskette:
Marktwert(Tag) - Marktwert(Vortag) muss der Spalte "Marktwertveraenderung" entsprechen.
Spieler ohne Zuordnung (z. B. inzwischen gewechselt) werden weggelassen und aufgelistet.
Braucht openpyxl (pip install openpyxl).
"""
import argparse
import csv
import os
import re
import sys
import unicodedata
from datetime import date, timedelta

ORDNER = "marktwerte"
BLAETTER = {"Bundesliga": "bundesliga", "2. Bundesliga": "2-bundesliga",
            "La Liga": "la-liga", "Frauen Bundesliga": "frauen-bundesliga",
            "Frauen-Bundesliga": "frauen-bundesliga"}
POSITION = {"TW": "1", "ABW": "2", "MF": "3", "ANG": "4"}
KOPF = ["Spieler-ID", "Spieler", "Verein", "Vereinsname", "Position", "Marktwert"]


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).lower()
    return "".join(c for c in s if c.isalnum())


def excel_lesen(pfad):
    import openpyxl
    wb = openpyxl.load_workbook(pfad, read_only=True, data_only=True)
    daten = {}
    for ws in wb.worksheets:
        liga = BLAETTER.get(ws.title.strip())
        if not liga:
            print("   ·  Blatt \"%s\" unbekannt - uebersprungen" % ws.title)
            continue
        zeilen = []
        for r in list(ws.iter_rows(values_only=True))[1:]:
            if not r or r[4] is None or not str(r[4]).strip().lstrip("-").isdigit():
                continue
            zeilen.append({"vn": r[0] or "", "nn": r[1] or "", "team": r[2] or "",
                           "pos": POSITION.get(str(r[3] or "").strip().upper()), "mw": int(r[4]),
                           "diff": int(r[5]) if r[5] not in (None, "") else None})
        daten[liga] = zeilen
    return daten


def tag_lesen(liga, tag):
    with open(os.path.join(ORDNER, liga, tag + ".csv"), encoding="utf-8-sig") as f:
        return list(csv.DictReader(f, delimiter=";"))


def name_passt(ref, z):
    s = norm(ref["Spieler"])
    voll = norm(z["vn"] + z["nn"])
    return s and (s == norm(z["nn"]) or s == voll or (len(s) >= 4 and (s in voll or norm(z["nn"]) in s)))


def zuordnen(zeilen, ref):
    """-> ({Zeilenindex: Ref-Zeile}, [nicht zugeordnete Indizes])"""
    nach_team = {}
    for r in ref:
        nach_team.setdefault(norm(r["Vereinsname"]), []).append(r)
    ergebnis, offen, benutzt = {}, [], set()
    for runde in (1, 2):
        for i, z in enumerate(zeilen):
            if i in ergebnis:
                continue
            frei = [r for r in nach_team.get(norm(z["team"]), []) if r["Spieler-ID"] not in benutzt]
            if runde == 1:
                kand = [r for r in frei if name_passt(r, z)]
                if len(kand) > 1 and z["pos"]:
                    kand = [r for r in kand if r["Position"] == z["pos"]] or kand
                if len(kand) > 1:
                    kand = [min(kand, key=lambda r: abs(int(r["Marktwert"]) - z["mw"]))]
            else:   # Name weicht ab: gleiche Position, Marktwert innerhalb 3 %, eindeutig
                kand = [r for r in frei if r["Position"] == z["pos"]
                        and abs(int(r["Marktwert"]) - z["mw"]) <= 0.03 * max(z["mw"], 1)]
            if len(kand) == 1:
                ergebnis[i] = kand[0]
                benutzt.add(kand[0]["Spieler-ID"])
    offen = [i for i in range(len(zeilen)) if i not in ergebnis]
    return ergebnis, offen


def main():
    ap = argparse.ArgumentParser(description="Alte Marktwerte aus Excel-Spielerlisten nachtragen")
    ap.add_argument("dateien", nargs="+")
    ap.add_argument("--erste", required=True, help="z. B. 56=2026-10-21")
    ap.add_argument("--pruefen", action="store_true")
    ap.add_argument("--ueberschreiben", action="store_true")
    a = ap.parse_args()

    nr0, datum0 = a.erste.split("=")
    nr0, datum0 = int(nr0), date.fromisoformat(datum0)
    listen = {}
    for pfad in a.dateien:
        m = re.search(r"(\d+)\.xlsx$", pfad)
        if not m:
            sys.exit("❌ Keine Nummer im Dateinamen: %s" % pfad)
        listen[int(m.group(1))] = pfad
    nummern = sorted(listen)
    if nummern != list(range(nummern[0], nummern[-1] + 1)):
        print("⚠️  Nummern nicht lueckenlos: %s" % nummern)
    daten = {n: excel_lesen(listen[n]) for n in nummern}
    datum = {n: (datum0 + timedelta(days=n - nr0)).isoformat() for n in nummern}
    print("Listen %d-%d = %s bis %s" % (nummern[0], nummern[-1], datum[nummern[0]], datum[nummern[-1]]))

    for liga in sorted(set(l for d in daten.values() for l in d)):
        print("\n== %s" % liga)
        ordner = os.path.join(ORDNER, liga)
        vorhanden = sorted(f[:-4] for f in os.listdir(ordner) if re.match(r"\d{4}-\d\d-\d\d\.csv$", f))
        spaeter = [t for t in vorhanden if t > datum[nummern[-1]]]
        if not spaeter:
            print("   ❌ keine Tagesdatei nach %s fuer die Zuordnung - uebersprungen" % datum[nummern[-1]])
            continue
        ref = tag_lesen(liga, spaeter[0])
        print("   Zuordnung ueber %s.csv (%d Spieler)" % (spaeter[0], len(ref)))
        # Tageskette pruefen
        for n in nummern[1:]:
            if n - 1 not in daten or liga not in daten[n - 1] or liga not in daten[n]:
                continue
            vor = {(z["vn"], z["nn"], z["team"]): z["mw"] for z in daten[n - 1][liga]}
            gesamt = ok = 0
            for z in daten[n][liga]:
                k = (z["vn"], z["nn"], z["team"])
                if k in vor and z["diff"] is not None:
                    gesamt += 1
                    ok += z["mw"] - vor[k] == z["diff"]
            if ok != gesamt:
                print("   ⚠️  Kette %d->%d: nur %d/%d Veraenderungen passen - Reihenfolge/Datum pruefen"
                      % (n - 1, n, ok, gesamt))
        fehlend = set()
        for n in nummern:
            zeilen = daten[n].get(liga)
            if not zeilen:
                continue
            zuo, offen = zuordnen(zeilen, ref)
            fehlend.update("%s %s (%s)" % (zeilen[i]["vn"], zeilen[i]["nn"], zeilen[i]["team"]) for i in offen)
            ausgabe = []
            for i, r in zuo.items():
                ausgabe.append([r["Spieler-ID"], r["Spieler"], r["Verein"], r["Vereinsname"], r["Position"], zeilen[i]["mw"]])
            ausgabe.sort(key=lambda z: -z[5])
            pfad = os.path.join(ordner, datum[n] + ".csv")
            status = "neu"
            if os.path.exists(pfad):
                status = "ersetzt" if a.ueberschreiben else "vorhanden - uebersprungen"
            print("   %s (Liste %d): %d/%d Spieler  %s" % (datum[n], n, len(zuo), len(zeilen), status))
            if a.pruefen or status.startswith("vorhanden"):
                continue
            with open(pfad + ".tmp", "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, delimiter=";")
                w.writerow(KOPF)
                w.writerows(ausgabe)
            os.replace(pfad + ".tmp", pfad)
        if fehlend:
            print("   Ohne Zuordnung (weggelassen): " + "; ".join(sorted(fehlend)))
    if a.pruefen:
        print("\n(nur Pruefung - nichts geschrieben)")


if __name__ == "__main__":
    main()
