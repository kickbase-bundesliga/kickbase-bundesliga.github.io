# -*- coding: utf-8 -*-
"""
Pokal-Automatik: Anmeldung ueber ein Google-Formular, Rundenplan, Auslosungen, Auswertung.

Einstellungen in config/<system>.json (nur Systeme mit "automatik": true werden angefasst):
    "pokal": {
        "automatik": true,
        "formular": "<Link zum Google-Formular>",
        "antworten_csv": "<veroeffentlichte CSV der Antworten-Tabelle>",
        "erste_auslosung": {"wochentag": 6, "uhr": "20:00"},    # 0 = Mo ... 6 = So (Standard: So 20 Uhr)
        "auslosung": {"wochentag": 2, "uhr": "20:00"},          # Folgerunden (Standard: Mi 20 Uhr)
        "fruehester_spieltag": 3                                 # Saison-Spieltag der ersten Runde
    }

Ablauf je Saison
  1. Anmeldung: zaehlt jede Formular-Antwort zwischen dem Anmeldeschluss der Vorsaison und dem
     Anmeldeschluss dieser Saison = Anstoss des 2. Spieltags der Saison. Gleiche ID mehrfach -> die
     erste zaehlt. Teilnehmen darf, wer in dieser Saison in einer Liga mit Pokal-Faktor > 0 spielt
     (KBL 1-5, KWBL alle). Der Name kommt aus der Datenbank.
     Der taegliche Spieltags-Lauf schreibt Anmeldeschluss und Termin der ersten Auslosung nach
     league_systems/<system>/cup/<SYSTEM>Cup_Anmeldung_<Saison>.json (fuer die Webseite).
  2. Am Tag der ersten Auslosung (Sonntag nach Anmeldeschluss) schreibt der Workflow
     "Pokal-Automatik" die Teilnehmerliste (<SYSTEM>Cup_Participants_<Saison>.csv) und den
     Rundenplan (<SYSTEM>Cup_Plan_<Saison>.json) und startet die Live-Auslosung (Workflow "Pokal").
  3. Rundenplan: so viele Runden wie noetig (128 Teilnehmer -> 7). Finale am vorletzten Spieltag der
     Saison, davor moeglichst alle 2 Spieltage, sonst jeder Spieltag, fruehestens Spieltag 3.
     Spieltage in englischen Wochen (Spiele Di-Do) sind nie Pokalspieltag. Jede Runde muss nach
     ihrer Auslosung beginnen.
  4. Der Spieltags-Lauf wertet die Runde aus, sobald ihr Spieltag eingespielt wird (nach der
     Kickbase-Abrechnung). Die naechste Runde lost "Pokal-Automatik" am folgenden Mittwoch 20 Uhr live
     aus. Ist es dafuer zu spaet (GitHub-Lauf verspaetet), wird sofort ohne Show gelost.

    python scripts/pokal_auto.py kbl status            Stand anzeigen (Anmeldungen, Plan)
    python scripts/pokal_auto.py kbl teilnehmer        Teilnehmerliste + Plan jetzt schreiben
    python scripts/pokal_auto.py kbl automatik         was heute faellig ist (fuer GitHub)
        --pruefen  nichts schreiben
"""
import argparse
import csv
import io
import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.append("./")
from scripts import utils  # noqa: E402

STANDARD = {"erste_auslosung": {"wochentag": 6, "uhr": "20:00"},
            "auslosung": {"wochentag": 2, "uhr": "20:00"},
            "fruehester_spieltag": 3}
LIVE_MIN_VORLAUF = timedelta(minutes=20)   # weniger -> sofort auslosen statt live
TAGE = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


# ---------------------------------------------------------------- Zeit

def jetzt():
    return datetime.now(timezone.utc)


def berlin(utc):
    import pokal
    return pokal.nach_berlin(utc)


def utc_aus_berlin(lokal):
    import pokal
    return pokal.nach_utc(lokal)


def iso(utc):
    return utc.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_lesen(text):
    import automatik
    return automatik.zeit_lesen(text) if text else None


def text_zeit(utc):
    b = berlin(utc)
    return "%s %s Uhr" % (TAGE[b.weekday()], b.strftime("%d.%m.%Y %H:%M"))


def naechster_termin(nach_utc, wochentag, uhr):
    """Erster Termin <wochentag> <uhr> (deutsche Zeit), der nach nach_utc liegt."""
    std, minute = [int(x) for x in str(uhr).split(":")[:2]]
    b = berlin(nach_utc)
    tag = b.replace(hour=std, minute=minute, second=0, microsecond=0)
    tag += timedelta(days=(int(wochentag) - tag.weekday()) % 7)
    t = utc_aus_berlin(tag)
    while t <= nach_utc:
        tag += timedelta(days=7)
        t = utc_aus_berlin(tag)
    return t


# ---------------------------------------------------------------- Einstellungen / Dateien

def einstellungen(system):
    config = utils.read_json("config/" + system)
    p = dict(STANDARD)
    p.update(config.get("pokal") or {})
    return p


def aktiv(system):
    return bool(einstellungen(system).get("automatik"))


def pfad(system, art, saison, endung="json"):
    return "league_systems/%s/cup/%sCup_%s_%s.%s" % (system, system.upper(), art, saison, endung)


def lesen(p):
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def schreiben(p, daten):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=2)
        f.write("\n")


def saisons_absteigend(system):
    return sorted(utils.read_json("config/" + system)["seasons"], key=lambda s: s["name"], reverse=True)


# ---------------------------------------------------------------- Spielplan

def regulaer(plan, tag):
    zeiten = plan.get(tag) or []
    nxt = plan.get(tag + 1)
    return [z for z in zeiten if not nxt or z < nxt[0]] or zeiten


def englische_woche(plan, tag):
    """Spieltag ueberwiegend Di-Do (deutsche Zeit) -> englische Woche."""
    zeiten = regulaer(plan, tag)
    if not zeiten:
        return False
    unter_woche = sum(1 for z in zeiten if berlin(z).weekday() in (1, 2, 3))
    return unter_woche * 2 > len(zeiten)


def abrechnung(system, letzter_anstoss):
    import automatik
    einst = utils.read_json("config/" + system).get("automatik") or {}
    if einst.get("abrechnung_uhr") is not None:
        return automatik.nach_abrechnung(einst["abrechnung_uhr"], einst.get("nach_abrechnung_minuten", 60))(letzter_anstoss)
    return letzter_anstoss + timedelta(hours=float(einst.get("wartezeit_stunden", 12)))


def anmeldeschluss(saison, plan):
    zweiter = int(saison["first_matchday"]) + 1
    if zweiter not in plan:
        return None
    return min(plan[zweiter])


def rundenplan(system, saison, plan, groesse, erste_auslosung):
    """-> [{"groesse", "spieltag" (Bundesliga), "kbl_spieltag", "auslosung"}] von der ersten Runde bis
    zum Finale. Wirft ValueError, wenn es nicht passt."""
    ein = einstellungen(system)
    erster, letzter = int(saison["first_matchday"]), int(saison["last_matchday"])
    folge = ein["auslosung"]
    runden = int(round(math.log(groesse, 2)))
    if 2 ** runden != groesse:
        raise ValueError("Rundengroesse %d ist keine Zweierpotenz" % groesse)

    def auslosung_nach(tag):
        """Termin der Auslosung, die auf die Runde an diesem Spieltag folgt."""
        return naechster_termin(abrechnung(system, max(regulaer(plan, tag))), folge["wochentag"], folge["uhr"])

    kand = [t for t in range(erster + int(ein["fruehester_spieltag"]) - 1, letzter)
            if t in plan and not englische_woche(plan, t)]
    kand = [t for t in kand if min(plan[t]) > erste_auslosung]
    if len(kand) < runden:
        raise ValueError("Nur %d moegliche Pokalspieltage fuer %d Runden" % (len(kand), runden))

    def suchen(abstand):
        gewaehlt = [kand[-1]]                       # Finale: vorletzter Spieltag (bzw. letzter moeglicher davor)
        for rest in range(runden - 1, 0, -1):
            spaeter = gewaehlt[0]
            ok = [c for c in kand if c < spaeter and auslosung_nach(c) < min(plan[spaeter])
                  and sum(1 for x in kand if x <= c) >= rest]
            if not ok:
                return None
            weit = [c for c in ok if c <= spaeter - abstand]
            gewaehlt.insert(0, (weit or ok)[-1])
        return gewaehlt

    tage = suchen(2) or suchen(1)
    if not tage:
        raise ValueError("Kein Rundenplan moeglich (zu wenige Spieltage)")
    ergebnis, termin = [], erste_auslosung
    for i, t in enumerate(tage):
        ergebnis.append({"groesse": groesse >> i, "spieltag": t, "kbl_spieltag": t - erster + 1,
                         "auslosung": iso(termin)})
        termin = auslosung_nach(t)
    return ergebnis


# ---------------------------------------------------------------- Anmeldung

def anmeldung_schreiben(system, saison, plan, log=print):
    """Vom taeglichen Spieltags-Lauf aufgerufen: Anmeldeschluss + erste Auslosung festhalten."""
    if not aktiv(system):
        return
    ein = einstellungen(system)
    schluss = anmeldeschluss(saison, plan)
    if schluss is None:
        return
    erste = naechster_termin(schluss, ein["erste_auslosung"]["wochentag"], ein["erste_auslosung"]["uhr"])
    # Fenster beginnt mit dem Anmeldeschluss der Vorsaison
    ab = None
    for s in saisons_absteigend(system):
        if s["name"] < saison["name"]:
            vor = lesen(pfad(system, "Anmeldung", s["name"]))
            ab = vor.get("schluss") if vor else None
            break
    # Rundenplaene fuer alle moeglichen Teilnehmerzahlen (der Workflow "Pokal-Automatik" braucht
    # dann keinen Kickbase-Zugang, die Webseite kann den voraussichtlichen Plan zeigen)
    plaene = {}
    for k in range(1, 9):
        try:
            plaene[str(2 ** k)] = rundenplan(system, saison, plan, 2 ** k, erste)
        except ValueError:
            pass
    neu = {"saison": saison["name"], "ab": ab, "schluss": iso(schluss), "auslosung": iso(erste),
           "formular": ein.get("formular"), "csv": ein.get("antworten_csv"), "plaene": plaene}
    p = pfad(system, "Anmeldung", saison["name"])
    if lesen(p) != neu:
        schreiben(p, neu)
        log("🏆 Pokal-Anmeldung %s: bis %s, erste Auslosung %s" % (saison["name"], text_zeit(schluss), text_zeit(erste)))


def antworten_laden(url):
    import requests
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


def zeitstempel_lesen(text):
    t = " ".join(str(text or "").split())
    for f in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return utc_aus_berlin(datetime.strptime(t, f))
        except ValueError:
            pass
    return None


def antworten_lesen(text):
    """CSV der Formular-Antworten -> [(Zeit UTC, ID-Text, Name)]."""
    zeilen = [z for z in csv.reader(io.StringIO(text)) if any(x.strip() for x in z)]
    if not zeilen:
        return []
    kopf = [k.lower() for k in zeilen[0]]
    sp_id = next((i for i, k in enumerate(kopf) if "id" in k.split() or "mitglied" in k or k.endswith(" id")
                  or k.startswith("id") or "kickbase id" in k), 1)
    sp_name = next((i for i, k in enumerate(kopf) if "name" in k and i != sp_id), 2)
    aus = []
    for z in zeilen[1:]:
        z = z + [""] * 3
        aus.append((zeitstempel_lesen(z[0]), z[sp_id].strip(), z[sp_name].strip()))
    return aus


def anmeldungen_auswerten(system, saison_name, antworten, ab, schluss):
    """-> (teilnehmer [(Zeit, ID, Name, Liga kurz)], abgelehnt [(ID, Name, Grund)])."""
    config = utils.read_json("config/" + system)
    faktor = {n: lc.get("cup_factor", 0) for lc in config["leagues"] for n in lc["names"]}
    db = utils.read_json("league_systems/%s/databases/%s_database" % (system, system))
    teilnehmer, abgelehnt, gesehen = [], [], set()
    for zeit, roh, name in sorted(antworten, key=lambda a: a[0] or datetime.max.replace(tzinfo=timezone.utc)):
        if zeit is None or (ab and zeit <= ab) or (schluss and zeit >= schluss):
            continue
        mid = "".join(ch for ch in roh if ch.isdigit())
        if not mid:
            abgelehnt.append((roh, name, "keine gueltige ID"))
            continue
        if mid in gesehen:
            continue
        gesehen.add(mid)
        m = db.get(mid)
        if not isinstance(m, dict):
            abgelehnt.append((mid, name, "ID nicht im %s-System" % system.upper()))
            continue
        liga = (m.get(saison_name) or {}).get("League")
        if not liga:
            abgelehnt.append((mid, m.get("Username") or name, "in dieser Saison in keiner Liga"))
            continue
        if not faktor.get(liga):
            abgelehnt.append((mid, m.get("Username") or name, "%s spielt nicht im Pokal" % liga_kurz(system, liga)))
            continue
        teilnehmer.append((zeit, mid, m.get("Username") or name, liga_kurz(system, liga)))
    return teilnehmer, abgelehnt


def teilnehmer_schreiben(system, saison, log=print, pruefen=False):
    """Anmeldungen holen, pruefen, Teilnehmerliste + Rundenplan schreiben. -> Anzahl Teilnehmer."""
    an = lesen(pfad(system, "Anmeldung", saison["name"]))
    if not an:
        raise SystemExit("❌ Keine Anmeldedaten fuer %s (schreibt der Spieltags-Lauf)." % saison["name"])
    if not an.get("csv"):
        raise SystemExit("❌ Kein Link zur Antworten-CSV in config/%s.json (pokal.antworten_csv)." % system)
    antworten = antworten_lesen(antworten_laden(an["csv"]))
    teilnehmer, abgelehnt = anmeldungen_auswerten(system, saison["name"], antworten,
                                                  iso_lesen(an.get("ab")), iso_lesen(an["schluss"]))
    log("📝 %d Antworten, %d Teilnehmer, %d abgelehnt" % (len(antworten), len(teilnehmer), len(abgelehnt)))
    for mid, name, grund in abgelehnt:
        log("   ✖ %s (%s): %s" % (name, mid, grund))
    if len(teilnehmer) < 2:
        raise SystemExit("❌ Zu wenige Teilnehmer (%d)." % len(teilnehmer))
    groesse = 2 ** (len(teilnehmer) - 1).bit_length()
    runden = (an.get("plaene") or {}).get(str(groesse))
    if not runden:
        raise SystemExit("❌ Kein Rundenplan fuer %d Teilnehmer moeglich - Pokal von Hand anlegen." % len(teilnehmer))
    for r in runden:
        log("   %-22s %d. Spieltag (%s. %s-Spieltag), Auslosung %s"
            % (rundenname(r["groesse"]), r["spieltag"], r["kbl_spieltag"], system.upper(), text_zeit(iso_lesen(r["auslosung"]))))
    if pruefen:
        return len(teilnehmer)
    with open(pfad(system, "Participants", saison["name"], "csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=",", quotechar="|")
        w.writerow(["Zeitstempel", "Kickbase-ID", "Name", "Liga"])
        for zeit, mid, name, liga in teilnehmer:
            w.writerow([berlin(zeit).strftime("%d.%m.%Y %H:%M:%S"), mid,
                        name.replace("|", "/").replace(",", " "), liga])
    schreiben(pfad(system, "Plan", saison["name"]),
              {"saison": saison["name"], "teilnehmer": len(teilnehmer), "runden": runden,
               "abgelehnt": [{"id": a, "name": b, "grund": c} for a, b, c in abgelehnt]})
    log("✅ Teilnehmerliste und Rundenplan %s geschrieben." % saison["name"])
    return len(teilnehmer)


def liga_kurz(system, liga):
    """'KWBL - Liga 3A' -> 'KWBL 3A' (wie league_system_kbl_cup.liga_kurz, ohne Bild-Pakete zu laden)."""
    if not liga:
        return ""
    rest = liga.split(" - ", 1)[1] if " - " in liga else liga
    return "%s %s" % (system.upper(), rest.replace("Liga ", "").strip())


def rundenname(n):
    return {2: "Finale", 4: "Halbfinale", 8: "Viertelfinale", 16: "Achtelfinale"}.get(n, "Runde der letzten %d" % n)


# ---------------------------------------------------------------- Auswertung (aus automatik.py)

def auswertung_spieltag(system, saison):
    """Bundesliga-Spieltag, an dem die aktuell ausgeloste Runde gespielt wird und noch nicht
    ausgewertet ist - sonst None. Nur fuer Pokale mit Rundenplan."""
    if not aktiv(system):
        return None
    plan = lesen(pfad(system, "Plan", saison["name"]))
    db = lesen(pfad(system, "Database", saison["name"]))
    if not plan or not db:
        return None
    runde = min(int(k) for k in db)
    if db[str(runde)].get("Winners"):
        return None
    for r in plan["runden"]:
        if r["groesse"] == runde:
            return int(r["spieltag"])
    return None


# ---------------------------------------------------------------- Auslosung (Workflow "Pokal-Automatik")

def faellig(system, now, log=print, pruefen=False):
    """-> None oder {"aktion": <Aktion im Workflow "Pokal">, "start": "JJJJ-MM-TT HH:MM"}"""
    import pokal
    if not aktiv(system):
        log("%s: Pokal-Automatik aus." % system.upper())
        return None
    saison = utils.get_current_season(system)
    live = pokal.live_lesen(system)
    if live and live.get("status") == "angekuendigt":
        log("%s: Auslosung schon angekuendigt (%s)." % (system.upper(), live.get("start")))
        return None
    db = lesen(pfad(system, "Database", saison["name"]))
    if db is None:
        an = lesen(pfad(system, "Anmeldung", saison["name"]))
        if not an:
            log("%s %s: noch kein Anmeldeschluss bekannt." % (system.upper(), saison["name"]))
            return None
        termin = iso_lesen(an["auslosung"])
        if berlin(now).date() < berlin(termin).date():
            log("%s %s: Anmeldung laeuft bis %s, Auslosung %s." % (system.upper(), saison["name"],
                text_zeit(iso_lesen(an["schluss"])), text_zeit(termin)))
            return None
        if now < iso_lesen(an["schluss"]):
            return None
        if not os.path.exists(pfad(system, "Participants", saison["name"], "csv")) or \
                not os.path.exists(pfad(system, "Plan", saison["name"])):
            teilnehmer_schreiben(system, saison, log, pruefen)
        live_moeglich, sofort = "Live-Auslosung terminieren", "Neuen Pokal anlegen"
    else:
        plan = lesen(pfad(system, "Plan", saison["name"]))
        if not plan:
            log("%s %s: Pokal ohne Rundenplan - Auslosung von Hand." % (system.upper(), saison["name"]))
            return None
        runde = min(int(k) for k in db)
        if runde <= 2:
            log("%s %s: Finale ist ausgelost." % (system.upper(), saison["name"]))
            return None
        if not db[str(runde)].get("Winners"):
            log("%s %s: %s noch ohne Ergebnis." % (system.upper(), saison["name"], rundenname(runde)))
            return None
        naechste = next((r for r in plan["runden"] if r["groesse"] == runde // 2), None)
        if not naechste:
            log("%s %s: %s nicht im Rundenplan." % (system.upper(), saison["name"], rundenname(runde // 2)))
            return None
        termin = iso_lesen(naechste["auslosung"])
        if berlin(now).date() < berlin(termin).date():
            log("%s %s: %s wird %s ausgelost." % (system.upper(), saison["name"], rundenname(runde // 2), text_zeit(termin)))
            return None
        live_moeglich, sofort = "Live-Auslosung terminieren", "Runde sofort auslosen"
    if termin - now >= LIVE_MIN_VORLAUF:
        log("%s: Live-Auslosung %s" % (system.upper(), text_zeit(termin)))
        return {"aktion": live_moeglich, "start": berlin(termin).strftime("%Y-%m-%d %H:%M")}
    log("%s: Termin %s zu knapp oder verpasst - sofort auslosen." % (system.upper(), text_zeit(termin)))
    return {"aktion": sofort, "start": ""}


def status(system):
    saison = utils.get_current_season(system)
    print("%s %s – Pokal-Automatik %s" % (system.upper(), saison["name"], "an" if aktiv(system) else "aus"))
    an = lesen(pfad(system, "Anmeldung", saison["name"]))
    if an:
        print("Anmeldung: ab %s bis %s, erste Auslosung %s" % (
            text_zeit(iso_lesen(an["ab"])) if an.get("ab") else "Beginn",
            text_zeit(iso_lesen(an["schluss"])), text_zeit(iso_lesen(an["auslosung"]))))
    else:
        print("Anmeldung: noch kein Anmeldeschluss bekannt")
    plan = lesen(pfad(system, "Plan", saison["name"]))
    if plan:
        for r in plan["runden"]:
            print("   %-22s %d. Spieltag, Auslosung %s" % (rundenname(r["groesse"]), r["spieltag"], text_zeit(iso_lesen(r["auslosung"]))))
    if an and an.get("csv"):
        try:
            antworten = antworten_lesen(antworten_laden(an["csv"]))
            t, a = anmeldungen_auswerten(system, saison["name"], antworten, iso_lesen(an.get("ab")), iso_lesen(an["schluss"]))
            print("Antworten in der Tabelle: %d, fuer %s gueltig: %d, abgelehnt: %d" % (len(antworten), saison["name"], len(t), len(a)))
            for mid, name, grund in a:
                print("   ✖ %s (%s): %s" % (name, mid, grund))
        except Exception as e:
            print("Antworten nicht lesbar:", e)


def main():
    p = argparse.ArgumentParser(description="Pokal-Automatik")
    p.add_argument("system", choices=utils.alle_systeme())
    p.add_argument("aktion", choices=["status", "teilnehmer", "automatik"])
    p.add_argument("--pruefen", action="store_true")
    a = p.parse_args()
    if a.aktion == "status":
        status(a.system)
    elif a.aktion == "teilnehmer":
        teilnehmer_schreiben(a.system, utils.get_current_season(a.system), pruefen=a.pruefen)
    else:
        import pokal
        erg = faellig(a.system, jetzt(), log=pokal.zusammenfassung, pruefen=a.pruefen)
        if erg and not a.pruefen:
            pokal.github_ausgabe(aktion=erg["aktion"], start=erg["start"])


if __name__ == "__main__":
    main()
