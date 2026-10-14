"""
Pokal ohne Rueckfragen - fuer den GitHub-Workflow "Pokal", geht aber auch lokal.

    python pokal.py kbl neu                         neuen Pokal der aktuellen Saison anlegen
                                                    (aus league_systems/kbl/cup/KBLCup_Participants_<Saison>.csv)
    python pokal.py kbl auslosen                    naechste Runde sofort auslosen
    python pokal.py kbl ankuendigen --start 20:00   Live-Auslosung auf der Webseite ankuendigen
          (--start "20.10. 20:00" fuer einen anderen Tag, --sekunden 5 = Zeit pro Kugel)
    python pokal.py kbl warten                      wartet bis kurz vor dem Start (fuer GitHub)
    python pokal.py kbl live-ziehen                 lost die angekuendigte Runde aus
    python pokal.py kbl absagen                     Ankuendigung zuruecknehmen

Ergebnisse auswerten bleibt bei automatik.py / update.py (--spieltag N --pokal).

Live-Auslosung: Die Webseite zeigt ab der Ankuendigung einen Countdown. Kurz vor dem Start wird
ausgelost und veroeffentlicht; ab der Startzeit zieht die Webseite Kugel fuer Kugel aus dem Lostopf.
Alle Besucher sehen dasselbe, weil die Anzeige an der Uhrzeit haengt.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.append("./")
from scripts import utils  # noqa: E402

VORLAUF_ZIEHUNG = timedelta(minutes=6)    # so lange vor dem Start wird ausgelost und veroeffentlicht
MIN_VORLAUF = timedelta(minutes=15)       # Ankuendigung mindestens so lange vor dem Start (GitHub braucht Zeit)
MAX_VORLAUF = timedelta(hours=5, minutes=40)  # ein GitHub-Lauf darf hoechstens 6 Stunden dauern


# ---------------------------------------------------------------- Zeit (deutsche Zeit ohne zoneinfo, Python 3.7)

def jetzt():
    return datetime.now(timezone.utc)


def _letzter_sonntag(jahr, monat):
    t = datetime(jahr, monat, 31)
    return t - timedelta(days=(t.weekday() + 1) % 7)


def berlin_versatz(lokal):
    """Stunden Unterschied zu UTC fuer eine deutsche Uhrzeit (Sommerzeit Ende Maerz bis Ende Oktober)."""
    beginn = _letzter_sonntag(lokal.year, 3).replace(hour=2)
    ende = _letzter_sonntag(lokal.year, 10).replace(hour=3)
    return 2 if beginn <= lokal < ende else 1


def nach_utc(lokal):
    return (lokal - timedelta(hours=berlin_versatz(lokal))).replace(tzinfo=timezone.utc)


def nach_berlin(utc):
    u = utc.astimezone(timezone.utc).replace(tzinfo=None)
    # Umstellung jeweils um 01:00 UTC am letzten Sonntag im Maerz bzw. Oktober
    sommer = (_letzter_sonntag(u.year, 3).replace(hour=1) <= u < _letzter_sonntag(u.year, 10).replace(hour=1))
    return u + timedelta(hours=2 if sommer else 1)


def text_zeit(utc):
    b = nach_berlin(utc)
    tage = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    return "%s %s Uhr" % (tage[b.weekday()], b.strftime("%d.%m.%Y %H:%M"))


def start_lesen(text, now=None):
    """'20:00' (heute), '20.10. 20:00', '20.10.2026 20:00' oder '2026-10-20 20:00' -> UTC."""
    now = now or jetzt()
    heute = nach_berlin(now)
    t = " ".join(str(text).strip().replace("Uhr", "").split())
    if not t:
        raise ValueError("Bitte eine Startzeit angeben, z. B. 20:00")
    datum_teil, _, zeit_teil = t.rpartition(" ")
    try:
        stunde, minute = [int(x) for x in zeit_teil.replace(".", ":").split(":")[:2]]
    except ValueError:
        raise ValueError("Uhrzeit nicht lesbar: %r (Beispiel: 20:00)" % zeit_teil)
    if not datum_teil:
        tag, monat, jahr = heute.day, heute.month, heute.year
    elif "-" in datum_teil:
        jahr, monat, tag = [int(x) for x in datum_teil.split("-")]
    else:
        teile = [x for x in datum_teil.split(".") if x]
        tag, monat = int(teile[0]), int(teile[1])
        jahr = int(teile[2]) if len(teile) > 2 else heute.year
        if jahr < 100:
            jahr += 2000
    return nach_utc(datetime(jahr, monat, tag, stunde, minute))


def iso(utc):
    return utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_lesen(text):
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- Dateien

def cup_pfad(system, saison):
    return "league_systems/%s/cup/%sCup_Database_%s" % (system, system.upper(), saison)


def live_pfad(system):
    return os.path.join("league_systems", system, "cup", "live_auslosung.json")


def live_lesen(system):
    p = live_pfad(system)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def live_schreiben(system, daten):
    with open(live_pfad(system), "w", encoding="utf-8") as f:
        json.dump(daten, f, indent=2, ensure_ascii=False)
        f.write("\n")


def runden_stand(system, saison):
    """-> (aktuelle Runde, Anzahl Sieger, naechste Runde) oder SystemExit mit verstaendlichem Grund."""
    pfad = cup_pfad(system, saison)
    if not os.path.exists(pfad + ".json"):
        raise SystemExit("❌ Fuer Saison %s gibt es noch keinen Pokal. Erst 'neu' ausfuehren." % saison)
    db = utils.read_json(pfad)
    runde = str(min(int(k) for k in db))
    if int(runde) <= 2:
        raise SystemExit("❌ Das Finale ist bereits ausgelost - es gibt keine weitere Runde.")
    sieger = db[runde].get("Winners") or []
    if not sieger:
        raise SystemExit("❌ Die Ergebnisse der Runde \"%s\" fehlen noch. Erst den Spieltag mit Pokal "
                         "einspielen (--spieltag N --pokal)." % rundenname(int(runde)))
    return int(runde), len(sieger), int(runde) // 2


def teilnehmer_csv(system, saison):
    return "league_systems/%s/cup/%sCup_Participants_%s.csv" % (system, system.upper(), saison)


def erste_runde_stand(system, saison):
    """Neuer Pokal: -> (Rundengroesse, Teilnehmer, Freilose) aus der Teilnehmerliste."""
    import csv
    pfad = teilnehmer_csv(system, saison)
    if not os.path.exists(pfad):
        raise SystemExit("❌ Teilnehmerliste fehlt: %s" % pfad)
    with open(pfad, newline="", encoding="utf8") as f:
        zeilen = [z for z in csv.reader(f) if any(x.strip() for x in z)]
    p = len(zeilen) - 1
    if p < 2:
        raise SystemExit("❌ Zu wenige Teilnehmer in %s." % pfad)
    runde = 2 ** (p - 1).bit_length()
    return runde, p, runde - p


def rundenname(n):
    return {2: "Finale", 4: "Halbfinale", 8: "Viertelfinale", 16: "Achtelfinale"}.get(n, "Runde der letzten %d" % n)


def github_ausgabe(**werte):
    ziel = os.environ.get("GITHUB_OUTPUT")
    if ziel:
        with open(ziel, "a", encoding="utf-8") as f:
            for k, v in werte.items():
                f.write("%s=%s\n" % (k, v))


def zusammenfassung(text):
    print(text)
    ziel = os.environ.get("GITHUB_STEP_SUMMARY")
    if ziel:
        with open(ziel, "a", encoding="utf-8") as f:
            f.write(text + "  \n")


# ---------------------------------------------------------------- Aktionen

def neu(system, saison):
    from scripts import league_system_kbl_cup as cup
    erste_runde_stand(system, saison)          # prueft die Teilnehmerliste
    if os.path.exists(cup_pfad(system, saison) + ".json"):
        raise SystemExit("❌ Fuer Saison %s gibt es schon einen Pokal." % saison)
    cup.create_new_cup(system, saison)
    runde, p, freilose = erste_runde_stand(system, saison)
    zusammenfassung("✅ Pokal %s %s angelegt: %s mit %d Teilnehmern, %d Freilose."
                    % (system.upper(), saison, rundenname(runde), p, freilose))
    return runde


def auslosen(system, saison):
    from scripts import league_system_kbl_cup as cup
    alt, anzahl, neu_runde = runden_stand(system, saison)
    cup.draw_new_round(system, saison)
    zusammenfassung("✅ %s ausgelost (%d Teilnehmer)." % (rundenname(neu_runde), anzahl))
    return neu_runde


def ankuendigen(system, saison, start_text, sekunden, github=False):
    # Gibt es fuer die Saison noch keinen Pokal, wird die erste Runde live gelost (Freilose zuerst)
    erste = not os.path.exists(cup_pfad(system, saison) + ".json")
    if erste:
        neu_runde, anzahl, freilose = erste_runde_stand(system, saison)
    else:
        alt, anzahl, neu_runde = runden_stand(system, saison)
        freilose = anzahl % 2
    live = live_lesen(system)
    if live and live.get("status") == "angekuendigt" and live.get("saison") == saison:
        raise SystemExit("❌ Es ist schon eine Auslosung angekuendigt (%s). Erst 'absagen'."
                         % text_zeit(iso_lesen(live["start"])))
    start = start_lesen(start_text)
    rest = start - jetzt()
    if rest < MIN_VORLAUF:
        raise SystemExit("❌ Start %s ist zu knapp - bitte mindestens %d Minuten im Voraus ankuendigen."
                         % (text_zeit(start), MIN_VORLAUF.seconds // 60))
    if github and rest > MAX_VORLAUF:
        raise SystemExit("❌ Start %s ist zu weit weg. Auf GitHub hoechstens ca. 5 Std. 40 Min. vorher "
                         "ankuendigen (ein Lauf darf maximal 6 Stunden dauern)." % text_zeit(start))
    sekunden = max(2, min(30, int(sekunden)))
    live_schreiben(system, {"saison": saison, "runde": neu_runde, "teilnehmer": anzahl, "freilose": freilose,
                            "erste_runde": erste, "start": iso(start), "sekunden": sekunden,
                            "status": "angekuendigt"})
    dauer = anzahl * sekunden
    zusammenfassung("📣 Live-Auslosung %s%s angekuendigt: %s, %d Kugeln (%d Freilose), %d Sek. pro Kugel (ca. %d Min.)."
                    % (rundenname(neu_runde), " (neuer Pokal)" if erste else "", text_zeit(start), anzahl,
                       freilose, sekunden, max(1, round(dauer / 60))))
    github_ausgabe(start=iso(start))


def warten(system):
    live = live_lesen(system)
    if not live or live.get("status") != "angekuendigt":
        raise SystemExit("❌ Keine angekuendigte Auslosung gefunden (vielleicht abgesagt).")
    ziel = iso_lesen(live["start"]) - VORLAUF_ZIEHUNG
    print("⏳ Warte bis %s (Start %s)" % (text_zeit(ziel), text_zeit(iso_lesen(live["start"]))))
    while True:
        rest = (ziel - jetzt()).total_seconds()
        if rest <= 0:
            break
        if rest > 600:
            print("   noch %d Min." % (rest // 60), flush=True)
        time.sleep(min(rest, 600))
    print("✅ Los geht's")


def live_ziehen(system, saison):
    live = live_lesen(system)
    if not live or live.get("status") != "angekuendigt":
        raise SystemExit("❌ Keine angekuendigte Auslosung gefunden (vielleicht abgesagt).")
    if live.get("saison") != saison:
        raise SystemExit("❌ Die Ankuendigung gehoert zu Saison %s, aktuell ist %s." % (live.get("saison"), saison))
    neu_runde = neu(system, saison) if live.get("erste_runde") else auslosen(system, saison)
    live.update({"runde": neu_runde, "status": "gezogen", "gezogen": iso(jetzt())})
    live_schreiben(system, live)
    zusammenfassung("🎱 Auslosung veroeffentlicht - die Webseite zieht ab %s Kugel fuer Kugel."
                    % text_zeit(iso_lesen(live["start"])))


def absagen(system):
    live = live_lesen(system)
    if not live or live.get("status") != "angekuendigt":
        zusammenfassung("Keine offene Ankuendigung - nichts zu tun.")
        return
    os.remove(live_pfad(system))
    zusammenfassung("🛑 Ankuendigung fuer %s zurueckgenommen." % text_zeit(iso_lesen(live["start"])))


def main():
    p = argparse.ArgumentParser(description="Pokal anlegen und auslosen")
    p.add_argument("system", choices=utils.alle_systeme())
    p.add_argument("aktion", choices=["neu", "auslosen", "ankuendigen", "warten", "live-ziehen", "absagen"])
    p.add_argument("--start", default="", help="Startzeit der Live-Auslosung, z. B. 20:00 oder '20.10. 20:00'")
    p.add_argument("--sekunden", default="5", help="Sekunden pro Kugel (2-30)")
    a = p.parse_args()
    saison = utils.get_current_season(a.system)["name"]
    github = bool(os.environ.get("GITHUB_ACTIONS"))
    try:
        if a.aktion == "neu":
            neu(a.system, saison)
        elif a.aktion == "auslosen":
            auslosen(a.system, saison)
        elif a.aktion == "ankuendigen":
            ankuendigen(a.system, saison, a.start, a.sekunden or "5", github)
        elif a.aktion == "warten":
            warten(a.system)
        elif a.aktion == "live-ziehen":
            live_ziehen(a.system, saison)
        elif a.aktion == "absagen":
            absagen(a.system)
    except ValueError as e:
        raise SystemExit("❌ %s" % e)


if __name__ == "__main__":
    main()
