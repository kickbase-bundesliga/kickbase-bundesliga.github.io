# -*- coding: utf-8 -*-
"""
Spieler-Aktionen sammeln (nur lokal, NICHT fuer GitHub)
======================================================

Holt fuer jeden Bundesliga-Spieler und Spieltag die Kickbase-Punkteverteilung
(z. B. "Pass ins letzte Drittel", "Ballverlust") und speichert sie pro Spieler
und Spieltag: zusammengefasst je Aktionsart Anzahl und Punkte (positive wie negative)
und zusaetzlich jede einzelne Aktion mit Spielminute und Halbzeit. In den CSV-Dateien
steht immer der zuletzt eingespielte Marktwert (kader.json); der Marktwert vom Abholtag
wird nur als Rohwert im Spieltag-JSON mitgespeichert.

    python scripts/aktionen_sammeln.py              alle fertigen, noch fehlenden Spiele holen
                                                    (beim ersten Lauf rueckwirkend die ganze Saison)
    python scripts/aktionen_sammeln.py --pruefen    nur anzeigen, was fertig/offen ist
    python scripts/aktionen_sammeln.py --neu 7      Spieltag 7 komplett neu holen
    python scripts/aktionen_sammeln.py --neu 1-7    Spieltage 1 bis 7 komplett neu holen
    python scripts/aktionen_sammeln.py --kader      nur Kader inkl. aktueller Marktwerte holen
    python scripts/aktionen_sammeln.py --csv        nur die beiden CSV-Dateien neu schreiben
    python scripts/aktionen_sammeln.py --nur 8-9    nur diese Spieltage holen (z. B. im Workflow "Aktionen export")

Ein Spiel wird erst geholt, wenn der Spieltag abgeschlossen ist:
  - regulaere Spiele: "wartezeit" Stunden (Standard 30) nach dem Anstoss des letzten
    regulaeren Spiels des Spieltags (Sonntagsspiel -> Montagabend, nach dem Kickbase-Abschluss)
  - Nachholspiele: "wartezeit" Stunden nach ihrem eigenen Anstoss

Ablage: aktionen/<Saison>/spieltag_NN.json, aktionen/aktionsarten.json und fuer Excel:
        aktionen/<Saison>/aktionen_gesamt.csv   (je Spieler, Spieltag und Aktionsart: Anzahl, Punkte)
        aktionen/<Saison>/aktionen_einzeln.csv  (jede Aktion mit Minute und Halbzeit)
Der Ordner aktionen/ steht in .gitignore und wird nie hochgeladen.
Zugang: der KBL-Admin (config/kbl.txt).
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.append("./")
from scripts.spieltag_extras import Api  # noqa: E402

WETTBEWERB = 1
ORDNER = "aktionen"
TAG_PARAMETER = "dayNumber"          # wird beim Start automatisch geprueft (siehe parameter_finden)
KANDIDATEN = ["dayNumber", "day", "matchDay", "md"]


def zeit(text):
    try:
        return datetime.strptime(str(text)[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def lade(pfad, standard):
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    return standard


def schreibe(pfad, daten):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, pfad)


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


def spielplan(api):
    d = api.get("/competitions/%d/matchdays" % WETTBEWERB)
    spiele = {}
    for tag in d.get("it", []) if isinstance(d, dict) else []:
        for m in tag.get("it", []):
            spiele[str(m["mi"])] = {"mi": str(m["mi"]), "tag": int(m.get("day") or tag.get("day")),
                                    "dt": m.get("dt"), "t1": str(m.get("t1")), "t2": str(m.get("t2")),
                                    "t1sy": m.get("t1sy"), "t2sy": m.get("t2sy"),
                                    "t1g": m.get("t1g"), "t2g": m.get("t2g"), "st": m.get("st")}
    return spiele


def fertig_ab(spiele, wartezeit):
    """mi -> Zeitpunkt, ab dem das Spiel als final gilt."""
    je_tag = {}
    for m in spiele.values():
        t = zeit(m["dt"])
        if t:
            je_tag.setdefault(m["tag"], []).append((t, m["mi"]))
    out = {}
    for tag, liste in je_tag.items():
        liste.sort()
        naechster = min((t for t, _ in je_tag.get(tag + 1, [])), default=None)
        regulaer = [(t, mi) for t, mi in liste if naechster is None or t < naechster] or liste
        ende_regulaer = regulaer[-1][0] + wartezeit
        for t, mi in liste:
            out[mi] = ende_regulaer if (t, mi) in regulaer else t + wartezeit
    return out


def kader_holen(api, team_ids, kader_alt):
    kader = {k: v for k, v in kader_alt.items() if k != "_stand"}
    for tid in sorted(team_ids, key=int):
        d = api.get("/competitions/%d/teams/%s/teamprofile" % (WETTBEWERB, tid))
        listen = list(spieler_listen(d)) if isinstance(d, dict) and "_fehler" not in d else []
        if not listen:
            print("   Achtung: Kader von Verein %s nicht abrufbar (%s)" % (tid, str(d)[:80]))
            continue
        alt = {s["i"]: s for s in kader.get(tid, [])}
        for s in listen[0]:
            alt[str(s["i"])] = {"i": str(s["i"]), "n": s.get("n") or s.get("ln") or str(s["i"]), "pos": s.get("pos"),
                                "mv": s.get("mv"), "st": s.get("st")}
        kader[tid] = sorted(alt.values(), key=lambda x: x["i"])
    return kader


def spiel_holen(api, spiel, kader):
    """Alle Spieler beider Vereine fuer dieses Spiel -> {pid: {...}}"""
    out = {}
    for tid in (spiel["t1"], spiel["t2"]):
        for s in kader.get(tid, []):
            d = api.get("/competitions/%d/playercenter/%s?%s=%d" % (WETTBEWERB, s["i"], TAG_PARAMETER, spiel["tag"]))
            if not isinstance(d, dict) or "_fehler" in d:
                continue
            if str(d.get("mi")) != spiel["mi"]:
                continue        # Spieler hat an diesem Spieltag nicht fuer diesen Verein gespielt
            events = d.get("events") or []
            # Halbzeit: Kickbase-Ereignis -10 = "Erste Halbzeit beendet"; Event-IDs steigen zeitlich
            pause = [int(e["ei"]) for e in events if e.get("eti") == -10 and str(e.get("ei", "")).isdigit()]
            aktionen, einzeln = {}, []
            for e in sorted(events, key=lambda x: int(x["ei"]) if str(x.get("ei", "")).isdigit() else 0):
                eti = str(e.get("eti"))
                a = aktionen.setdefault(eti, [0, 0])
                a[0] += 1
                a[1] += e.get("p") or 0
                mt = e.get("mt")
                if pause and str(e.get("ei", "")).isdigit():
                    hz = 1 if int(e["ei"]) <= pause[0] else 2
                else:
                    hz = 1 if (mt or 0) <= 45 else 2
                einzeln.append([int(e.get("eti") or 0), mt, e.get("p") or 0, hz])
            dabei = any(int(k) >= 0 for k in aktionen) or d.get("p")
            if not dabei:
                continue        # nur auf der Bank oder nicht im Kader
            out[s["i"]] = {"n": d.get("n") or s["n"], "tid": str(d.get("tid") or tid), "pos": s.get("pos"),
                           "mv": s.get("mv"),     # Marktwert beim Abholen (Kader wird bei jedem Lauf neu geholt)
                           "mi": spiel["mi"], "p": d.get("p") or sum(a[1] for a in aktionen.values()),
                           "a": aktionen, "e": einzeln}
    return out


def parameter_finden(api, spiel, kader):
    """Prueft, mit welchem Parameter Kickbase das Spiel des gewuenschten Spieltags liefert
    (und nicht einfach das neueste Spiel des Spielers)."""
    global TAG_PARAMETER
    bericht = []
    spieler = (kader.get(spiel["t1"]) or [])[:6] + (kader.get(spiel["t2"]) or [])[:6]
    for s in spieler:
        for par in KANDIDATEN:
            d = api.get("/competitions/%d/playercenter/%s?%s=%d" % (WETTBEWERB, s["i"], par, spiel["tag"]))
            mi = d.get("mi") if isinstance(d, dict) else None
            bericht.append("   %-10s Spieler %-8s -> Spiel %s (%s)" % (par, s["i"], mi, (d or {}).get("md") if isinstance(d, dict) else d))
            if str(mi) == spiel["mi"]:
                TAG_PARAMETER = par
                print("Spieltag-Parameter: %s (geprueft an ST %d, %s-%s)" % (par, spiel["tag"], spiel["t1sy"], spiel["t2sy"]))
                return True
    print("Kein Parameter liefert das Spiel von ST %d (%s-%s, Spiel %s). Gepruefte Antworten:"
          % (spiel["tag"], spiel["t1sy"], spiel["t2sy"], spiel["mi"]))
    print("\n".join(bericht[:24]))
    return False


POSITION = {1: "Tor", 2: "Abwehr", 3: "Mittelfeld", 4: "Sturm"}


def ohne_stornos(events):
    """Kickbase korrigiert eine falsch erfasste Aktion mit einer Gegenbuchung: gleiche Aktion,
    gleiche Minute, entgegengesetzte Punkte. Beide Buchungen fallen heraus (die Rohdaten im
    JSON bleiben unveraendert). Liefert die bereinigte Liste und die Zahl der Stornopaare."""
    weg = set()
    for i, (eti, mt, p, hz) in enumerate(events):
        if not p or eti <= 0:
            continue
        for j in range(i):
            e = events[j]
            if j not in weg and e[0] == eti and e[1] == mt and e[2] == -p:
                weg |= {i, j}
                break
    return [e for i, e in enumerate(events) if i not in weg], len(weg) // 2


def csv_schreiben(saison_ordner, arten, vereine, kader):
    gesamt, einzeln, stornos = [], [], 0
    kader_mv = {str(x["i"]): x.get("mv") for k, v in kader.items() if k != "_stand" for x in v}
    kader_stand = str(kader.get("_stand") or "")[:10]
    for datei in sorted(os.listdir(saison_ordner)):
        if not (datei.startswith("spieltag_") and datei.endswith(".json")):
            continue
        d = lade(os.path.join(saison_ordner, datei), {})
        for pid, s in d.get("spieler", {}).items():
            sp = d.get("spiele", {}).get(s["mi"], {})
            verein = vereine.get(s["tid"], s["tid"])
            gegner = sp.get("t2sy") if s["tid"] == str(sp.get("t1")) else sp.get("t1sy")
            heim = "Heim" if s["tid"] == str(sp.get("t1")) else "Auswaerts"
            pos = POSITION.get(s.get("pos"), s.get("pos") or "")
            # Marktwert immer der zuletzt eingespielte (kader.json), nie der vom Spieltag
            mv, stand = kader_mv.get(pid), kader_stand
            basis = [d["spieltag"], pid, s["n"], verein, gegner or "", heim, pos, mv if mv is not None else "", stand]
            events, n = ohne_stornos([e for e in s.get("e", []) if e[0] >= 0])   # nur Spieleraktionen
            stornos += n
            summe = {}
            for eti, mt, pkt, hz in events:
                a = summe.setdefault(eti, [0, 0])
                a[0] += 1
                a[1] += pkt
                einzeln.append(basis + [eti, arten.get(str(eti), ""), mt, hz, pkt])
            for eti, (anz, pkt) in sorted(summe.items()):
                gesamt.append(basis + [eti, arten.get(str(eti), ""), anz, pkt])
    kopf = ["Spieltag", "Spieler-ID", "Spieler", "Verein", "Gegner", "Heim/Auswaerts", "Position",
            "Marktwert", "Marktwert-Stand", "Aktion-ID", "Aktion"]
    for name, zeilen, rest in (("aktionen_gesamt.csv", gesamt, ["Anzahl", "Punkte"]),
                               ("aktionen_einzeln.csv", einzeln, ["Minute", "Halbzeit", "Punkte"])):
        with open(os.path.join(saison_ordner, name), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(kopf + rest)
            w.writerows(zeilen)
    return len(gesamt), len(einzeln), stornos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pruefen", action="store_true")
    ap.add_argument("--neu", action="append", default=[], help="Spieltag oder Bereich, z. B. 7 oder 1-7")
    ap.add_argument("--nur", action="append", default=[], help="nur diese Spieltage holen, z. B. 8-9")
    ap.add_argument("--wartezeit", type=float, default=30)
    ap.add_argument("--kader", action="store_true", help="nur Kader inkl. Marktwerte aktualisieren")
    ap.add_argument("--csv", action="store_true", help="nur die CSV-Dateien aus den gespeicherten Spieltagen neu schreiben")
    a = ap.parse_args()

    api = Api("kbl")
    now = datetime.now(timezone.utc)
    spiele = spielplan(api)
    if not spiele:
        sys.exit("Spielplan nicht lesbar.")
    erstes = min(zeit(m["dt"]) for m in spiele.values() if zeit(m["dt"]))
    saison = "%d-%02d" % (erstes.year, (erstes.year + 1) % 100)
    saison_ordner = os.path.join(ORDNER, saison)
    ab = fertig_ab(spiele, timedelta(hours=a.wartezeit))
    vereine = {}
    for m in spiele.values():
        vereine[m["t1"]] = m["t1sy"]
        vereine[m["t2"]] = m["t2sy"]

    def tagdatei(tag):
        return os.path.join(saison_ordner, "spieltag_%02d.json" % tag)

    neu = []
    for x in a.neu:
        von, _, bis = str(x).partition("-")
        neu += list(range(int(von), int(bis or von) + 1))
    for tag in neu:
        if os.path.exists(tagdatei(tag)):
            os.remove(tagdatei(tag))
            print("Spieltag %d wird neu geholt." % tag)

    nur = []
    for x in a.nur:
        von, _, bis = str(x).partition("-")
        nur += list(range(int(von), int(bis or von) + 1))
    offen = []
    for mi, m in sorted(spiele.items(), key=lambda x: (x[1]["tag"], x[1]["dt"] or "")):
        fertig = mi in ab and now >= ab[mi]
        schon = mi in lade(tagdatei(m["tag"]), {}).get("spiele", {})
        if fertig and not schon and (not nur or m["tag"] in nur):
            offen.append(m)
    tage = sorted(set(m["tag"] for m in offen))
    print("Saison %s: %d Spiele fertig und noch nicht geholt (Spieltage %s)" % (
        saison, len(offen), ", ".join(map(str, tage)) or "-"))
    if a.kader:
        kader = kader_holen(api, set(vereine), lade(os.path.join(saison_ordner, "kader.json"), {}))
        kader["_stand"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        schreibe(os.path.join(saison_ordner, "kader.json"), kader)
        mit = sum(1 for k, v in kader.items() if k != "_stand" for s in v if s.get("mv"))
        print("Kader aktualisiert: %d Spieler mit Marktwert." % mit)
        return
    if a.csv:
        arten = lade(os.path.join(ORDNER, "aktionsarten.json"), {})
        n, m, st = csv_schreiben(saison_ordner, arten, vereine, lade(os.path.join(saison_ordner, "kader.json"), {}))
        print("CSV neu geschrieben: %d / %d Zeilen, %d stornierte Aktionen herausgerechnet." % (n, m, st))
        return
    if a.pruefen or not offen:
        return

    arten_roh = api.get("/live/eventtypes")
    arten = {str(x["i"]): x.get("ti") for x in (arten_roh.get("it") or [])} if isinstance(arten_roh, dict) else {}
    if arten:
        schreibe(os.path.join(ORDNER, "aktionsarten.json"), arten)
    else:
        arten = lade(os.path.join(ORDNER, "aktionsarten.json"), {})

    kader = kader_holen(api, set(vereine), lade(os.path.join(saison_ordner, "kader.json"), {}))
    kader["_stand"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    schreibe(os.path.join(saison_ordner, "kader.json"), kader)
    print("Kader: %d Vereine, %d Spieler" % (len(kader) - 1, sum(len(v) for k, v in kader.items() if k != "_stand")))

    if not parameter_finden(api, offen[0], kader):
        sys.exit("Abbruch - bitte die Ausgabe oben an Claude geben.")

    for tag in tage:
        d = lade(tagdatei(tag), {"spieltag": tag, "spiele": {}, "spieler": {}})
        for m in [x for x in offen if x["tag"] == tag]:
            if not kader.get(m["t1"]) or not kader.get(m["t2"]):
                print("   ST %2d  %s-%s  uebersprungen (Kader fehlt), naechstes Mal erneut" % (tag, m["t1sy"], m["t2sy"]))
                continue
            spieler = spiel_holen(api, m, kader)
            if not spieler:
                print("   ST %2d  %s-%s  keine Spielerdaten erhalten - nicht gespeichert, naechstes Mal erneut"
                      % (tag, m["t1sy"], m["t2sy"]))
                continue
            d["spieler"].update(spieler)
            d["spiele"][m["mi"]] = {k: m[k] for k in ("t1", "t2", "t1sy", "t2sy", "t1g", "t2g", "dt")}
            d["spiele"][m["mi"]]["abgerufen"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            d["spiele"][m["mi"]]["spieler"] = len(spieler)
            schreibe(tagdatei(tag), d)          # nach jedem Spiel sichern
            print("   ST %2d  %s-%s  %d Spieler" % (tag, m["t1sy"], m["t2sy"], len(spieler)))
    n, m, st = csv_schreiben(saison_ordner, arten, vereine, kader)
    print("Fertig. %d API-Anfragen. aktionen_gesamt.csv: %d Zeilen, aktionen_einzeln.csv: %d Zeilen "
          "(%d stornierte Aktionen herausgerechnet)." % (api.anfragen, n, m, st))


if __name__ == "__main__":
    main()
