"""
Neue Saison anlegen - automatisch (aus automatik.py) oder von Hand / per Workflow "Neue Saison".

    python scripts/neue_saison.py kbl --pruefen         nur anzeigen, was passieren wuerde
    python scripts/neue_saison.py kbl                   anlegen, wenn die alte Saison fertig ist
          zusaetzlich: --letzter 14       letzter Bundesliga-Spieltag der neuen Saison selbst festlegen
                       --erzwingen        Pruefungen (alte Saison fertig, Pokal fertig) uebergehen
    python scripts/neue_saison.py kbl --zuruecknehmen   zuletzt angelegte Saison wieder entfernen
                                                        (nur solange sie noch keine Punkte hat)

Was passiert beim Anlegen?
  1. Pruefen, ob die alte Saison fertig ist:
       - letzter Spieltag eingespielt (automatik_status.json),
       - alle Spiele dieses Spieltags abgerechnet, Nachkontrolle vorbei (nachkontrolle_stunden),
       - Pokal der alten Saison bis zum Finale ausgewertet (falls es einen gibt).
  2. Neue Saison aus dem Kickbase-Spielplan ableiten:
       - nach einer Hinrunde (B): Rueckrunde (Jahr+1)A = letzter Spieltag + 1 bis Saisonende,
       - nach einer Rueckrunde (A): Hinrunde (Jahr)B = Spieltag 1 bis zur Winterpause
         (groesste Luecke im Spielplan zwischen November und Januar; ueberschreibbar mit --letzter
         oder in der Config: "automatik": {"winterpause_nach": 14}). Gibt Kickbase noch den alten
         Spielplan heraus, wird gewartet.
  3. Saison oben in config/<system>.json eintragen.
  4. Datenbank: alle Manager, die gerade in den Ligen sind, bekommen den Saison-Eintrag; wer in
     keiner Liga mehr ist, verliert seine aktuelle Liga. Wer erst spaeter in eine Liga wechselt
     oder neu dazukommt, wird beim ersten Spieltag automatisch ergaenzt (fill_database) - die
     Manager koennen also nach dem Anlegen in Ruhe umziehen.

Automatisch laeuft das nur fuer Systeme mit "automatik": {"neue_saison": true} in der Config.
"""
import argparse
import os
import re
import sys
from datetime import timedelta

sys.path.append("./")
from scripts import utils  # noqa: E402

NAME = re.compile(r"^(\d{4})([AB])$")
WINTER_MONATE = (11, 12, 1)
MIN_WINTERPAUSE = timedelta(days=14)
NEUER_SPIELPLAN = timedelta(days=60)   # Spieltag 1 hoechstens so lange her -> Spielplan der neuen Saison


class Warten(Exception):
    """Neue Saison (noch) nicht moeglich - Grund steht im Text."""


# ---------------------------------------------------------------- Ableiten

def naechster_name(name):
    m = NAME.match(name or "")
    if not m:
        raise Warten("Saisonname \"%s\" passt nicht zum Schema JJJJA/JJJJB - bitte von Hand anlegen." % name)
    jahr, teil = int(m.group(1)), m.group(2)
    return "%dA" % (jahr + 1) if teil == "B" else "%dB" % jahr


def regulaere_zeiten(plan, tag):
    """Anstosszeiten eines Spieltags ohne Nachholspiele (die nach Beginn des naechsten Spieltags)."""
    zeiten = plan.get(tag) or []
    naechster = plan.get(tag + 1)
    if not naechster:
        return zeiten
    return [z for z in zeiten if z < naechster[0]] or zeiten


def winterpause(plan):
    """-> letzter Spieltag vor der Winterpause (groesste Luecke Nov-Jan, mind. 14 Tage) oder None."""
    beste, beste_luecke = None, MIN_WINTERPAUSE
    for tag in sorted(plan):
        if tag + 1 not in plan:
            continue
        ende = max(regulaere_zeiten(plan, tag))
        if ende.month not in WINTER_MONATE:
            continue
        luecke = min(plan[tag + 1]) - ende
        if luecke >= beste_luecke:
            beste, beste_luecke = tag, luecke
    return beste


def vorschlag(config, alt, plan, now, letzter=None):
    """-> (neue Saison als dict, Hinweise). Wirft Warten, wenn es noch nicht geht."""
    from automatik import berlin
    name = naechster_name(alt["name"])
    if any(s["name"] == name for s in config["seasons"]):
        raise Warten("Saison %s steht schon in der Config." % name)
    hinweise = []
    if not plan:
        raise Warten("Spielplan ist leer.")
    if name.endswith("A"):
        erster = int(alt["last_matchday"]) + 1
        if letzter is None:
            letzter = max(plan)
        if erster not in plan:
            raise Warten("Spieltag %d steht nicht im Kickbase-Spielplan." % erster)
    else:
        erster = 1
        if 1 not in plan or min(plan[1]) < now - NEUER_SPIELPLAN:
            raise Warten("Kickbase zeigt noch den Spielplan der alten Saison - neue Hinrunde folgt, "
                         "sobald der neue Spielplan da ist.")
        if letzter is None:
            letzter = (config.get("automatik") or {}).get("winterpause_nach") or winterpause(plan)
            if letzter is None:
                raise Warten("Winterpause im Spielplan nicht gefunden - bitte letzten Spieltag angeben "
                             "(--letzter bzw. Feld im Workflow).")
            hinweise.append("Winterpause nach Spieltag %d erkannt (letztes Spiel %s, weiter %s)."
                            % (int(letzter), berlin(max(regulaere_zeiten(plan, int(letzter)))),
                               berlin(min(plan[int(letzter) + 1])) if int(letzter) + 1 in plan else "?"))
    letzter = int(letzter)
    if letzter < erster:
        raise Warten("Letzter Spieltag %d liegt vor dem ersten (%d)." % (letzter, erster))
    if erster in plan:
        beginn = min(plan[erster])
        if beginn <= now:
            hinweise.append("⚠️ Spieltag %d hat schon begonnen (%s) - fertige Spieltage holt der "
                            "naechste Lauf nach." % (erster, berlin(beginn)))
        else:
            hinweise.append("Erster Spieltag %d beginnt %s." % (erster, berlin(beginn)))
    neu = {"name": name, "matchday_number": str(letzter - erster + 1),
           "first_matchday": str(erster), "last_matchday": str(letzter)}
    return neu, hinweise


# ---------------------------------------------------------------- Pruefungen

def alte_saison_fertig(system, alt, plan, now, fenster, wartezeit):
    """-> Liste von Gruenden, warum noch nicht (leer = fertig)."""
    import automatik
    from automatik import berlin
    gruende = []
    letzter = int(alt["last_matchday"])
    bisher, quelle = automatik.letzter_verarbeiteter(system, alt)
    if bisher < letzter:
        gruende.append("Saison %s ist erst bis Spieltag %d eingespielt (letzter: %d)." % (alt["name"], bisher, letzter))
        return gruende
    # alle Spiele des letzten Spieltags (auch Nachholspiele) abgerechnet?
    for z in plan.get(letzter) or []:
        bereit = wartezeit(z) if callable(wartezeit) else z + wartezeit
        if bereit > now:
            gruende.append("Spiel vom %d. Spieltag (%s) ist erst ab %s abgerechnet." % (letzter, berlin(z), berlin(bereit)))
            break
    # Nachkontrolle vorbei?
    wann = (automatik.status_lesen(system, alt).get("eingespielt_am") or {}).get(str(letzter))
    t = automatik.zeit_lesen(wann) if wann else None
    if t is None:
        if quelle != "Statusdatei":
            gruende.append("Kein Einspiel-Zeitpunkt fuer Spieltag %d bekannt - Nachkontrolle unklar." % letzter)
    elif now - t <= fenster:
        gruende.append("Nachkontrolle von Spieltag %d laeuft noch bis %s." % (letzter, berlin(t + fenster)))
    return gruende


def pokal_fertig(system, alt):
    """-> None (fertig oder kein Pokal) oder Grund."""
    pfad = "league_systems/%s/cup/%sCup_Database_%s.json" % (system, system.upper(), alt["name"])
    if not os.path.exists(pfad):
        return None
    db = utils.read_json(pfad[:-5])
    runde = min(int(k) for k in db)
    if runde == 2 and (db["2"].get("Winners") or []):
        return None
    namen = {2: "Finale", 4: "Halbfinale", 8: "Viertelfinale", 16: "Achtelfinale"}
    return ("Pokal %s ist noch nicht fertig (%s ohne Ergebnis) - erst den Spieltag mit Pokalrunde "
            "einspielen." % (alt["name"], namen.get(runde, "Runde der letzten %d" % runde)))


# ---------------------------------------------------------------- Schreiben

def block(neu):
    return ('\n        {\n'
            '            "name": "%s",\n'
            '            "matchday_number": "%s",\n'
            '            "first_matchday": "%s",\n'
            '            "last_matchday": "%s",\n'
            '            "leagues": [\n'
            '                {}\n'
            '            ]\n'
            '        },') % (neu["name"], neu["matchday_number"], neu["first_matchday"], neu["last_matchday"])


def config_eintragen(system, neu):
    """Saison oben in die seasons-Liste einfuegen; Rest der Datei bleibt, wie er ist."""
    import json
    pfad = os.path.join("config", system + ".json")
    with open(pfad, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'"seasons"\s*:\s*\[', text)
    if not m:
        raise SystemExit("❌ \"seasons\" in %s nicht gefunden." % pfad)
    neu_text = text[:m.end()] + block(neu) + text[m.end():]
    daten = json.loads(neu_text)                       # muss gueltiges JSON bleiben
    if daten["seasons"][0]["name"] != neu["name"]:
        raise SystemExit("❌ Eintragen in %s fehlgeschlagen." % pfad)
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(neu_text)


def config_austragen(system, name):
    import json
    pfad = os.path.join("config", system + ".json")
    with open(pfad, encoding="utf-8") as f:
        text = f.read()
    m = re.search(r'\{\s*"name"\s*:\s*"%s".*?\}\s*\]\s*\}\s*,?' % re.escape(name), text, re.S)
    if not m:
        raise SystemExit("❌ Saison %s in %s nicht gefunden." % (name, pfad))
    neu_text = text[:m.start()] + text[m.end():]
    neu_text = re.sub(r'("seasons"\s*:\s*\[)\s*\n', r'\1\n', neu_text, count=1)
    daten = json.loads(neu_text)
    if any(s["name"] == name for s in daten["seasons"]):
        raise SystemExit("❌ Austragen aus %s fehlgeschlagen." % pfad)
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(neu_text)


def datenbank_ergaenzen(system, log):
    """Wie league_system_manager.add_new_season, mit Uebersicht je Liga."""
    from scripts import league_system_manager as lsm
    pfad = "league_systems/%s/databases/%s_database" % (system, system)
    config = utils.read_json("config/" + system)
    database = utils.read_json(pfad)
    _, leagues, adm_id, kickbase = utils.login_account(system)
    soll = {n: sum(lc.get("distribution") or []) for lc in config["leagues"] for n in lc["names"]}
    gueltig = utils.get_valid_league_names(system)
    ids, wo = [], {}
    for league in sorted(leagues, key=lambda l: l.name):
        if league.name not in gueltig:
            continue
        mgr = [m for m in kickbase.league_users(league) if str(m.i) != str(adm_id)]
        for m in mgr:
            ids.append(int(m.i))
            wo.setdefault(int(m.i), []).append(league.name)
        log("   %s: %d Manager%s" % (league.name, len(mgr),
                                    "" if soll.get(league.name) in (None, 0, len(mgr)) else " (Zonen: %d)" % soll[league.name]))
    vorher = set(database)
    lsm.change_database(ids, database, config)
    # wer in keiner Liga mehr ist, verliert seine aktuelle Liga (wie remove_players_who_left, nur leiser)
    raus = 0
    for key, d in database.items():
        if int(key) not in ids and isinstance(d, dict) and (d.get("Info") or {}).get("League") is not None:
            d["Info"]["League"] = None
            raus += 1
    utils.write_json(pfad, database)
    if raus:
        log("➖ %d Manager sind in keiner Liga mehr." % raus)
    neu = len(set(str(k) for k in database) - set(str(k) for k in vorher))
    doppelt = {k: v for k, v in wo.items() if len(v) > 1}
    log("✅ Datenbank: %d Manager in den Ligen, davon %d neu." % (len(set(ids)), neu))
    if doppelt:
        log("ℹ️  %d Manager sind gerade in mehreren Ligen (Umzug laeuft) - zaehlt erst ab dem ersten Spieltag."
            % len(doppelt))


def datenbank_austragen(system, name):
    pfad = "league_systems/%s/databases/%s_database" % (system, system)
    database = utils.read_json(pfad)
    for d in database.values():
        s = d.get(name) if isinstance(d, dict) else None
        if isinstance(s, dict) and (any(s.get("MdPoints") or []) or s.get("League")):
            raise SystemExit("❌ Saison %s hat schon Daten - zuruecknehmen nicht moeglich." % name)
    for d in database.values():
        if isinstance(d, dict):
            d.pop(name, None)
    utils.write_json(pfad, database)


# ---------------------------------------------------------------- Ablauf

def einstellungen(config):
    import automatik
    einst = config.get("automatik") or {}
    if einst.get("abrechnung_uhr") is not None:
        wartezeit = automatik.nach_abrechnung(einst["abrechnung_uhr"], einst.get("nach_abrechnung_minuten", 60))
    else:
        wartezeit = timedelta(hours=float(einst.get("wartezeit_stunden", 12)))
    fenster = timedelta(hours=float(einst.get("nachkontrolle_stunden", 50)))
    return wartezeit, fenster


def spielplan(system, config):
    import automatik
    from scripts.spieltag_extras import Api
    api = Api(system)
    wettbewerb, _ = automatik.wettbewerb_ermitteln(system, config, api)
    return automatik.spielplan_lesen(api.get("/competitions/%d/matchdays" % wettbewerb))


def anlegen(system, log, plan=None, nur_pruefen=False, erzwingen=False, letzter=None, now=None):
    """Prueft und legt ggf. an. -> True, wenn eine neue Saison eingetragen wurde."""
    import automatik
    now = now or automatik.jetzt()
    config = utils.read_json("config/" + system)
    alt = utils.get_current_season(system)
    wartezeit, fenster = einstellungen(config)
    if plan is None:
        plan = spielplan(system, config)

    gruende = alte_saison_fertig(system, alt, plan, now, fenster, wartezeit)
    p = pokal_fertig(system, alt)
    if p:
        gruende.append(p)
    try:
        neu, hinweise = vorschlag(config, alt, plan, now, letzter)
    except Warten as e:
        log("⏳ Neue Saison: %s" % e)
        return False

    log("🗓️  Neue Saison %s: Spieltage %s-%s (%s Spieltage)"
        % (neu["name"], neu["first_matchday"], neu["last_matchday"], neu["matchday_number"]))
    for h in hinweise:
        log("   " + h)
    if gruende:
        for g in gruende:
            log(("   ⚠️ (uebergangen) " if erzwingen else "   ⏳ ") + g)
        if not erzwingen:
            log("   Neue Saison wird angelegt, sobald das erledigt ist.")
            return False
    if nur_pruefen:
        log("   (nur Pruefung - nichts geaendert)")
        return False

    config_eintragen(system, neu)
    log("✅ Saison %s in config/%s.json eingetragen." % (neu["name"], system))
    datenbank_ergaenzen(system, log)
    log("ℹ️  Manager koennen jetzt in ihre neuen Ligen wechseln - Zuordnung erfolgt am ersten Spieltag.")
    return True


def zuruecknehmen(system, log, nur_pruefen=False):
    s = utils.get_current_season(system)
    log("↩️  Saison %s zuruecknehmen" % s["name"])
    if nur_pruefen:
        log("   (nur Pruefung - nichts geaendert)")
        return False
    datenbank_austragen(system, s["name"])
    config_austragen(system, s["name"])
    log("✅ Saison %s entfernt. Aktuell ist wieder %s." % (s["name"], utils.get_current_season(system)["name"]))
    return True


def main():
    import automatik
    p = argparse.ArgumentParser(description="Neue Saison anlegen")
    p.add_argument("system", choices=utils.alle_systeme())
    p.add_argument("--pruefen", action="store_true", help="nur anzeigen, nichts aendern")
    p.add_argument("--erzwingen", action="store_true", help="Pruefungen uebergehen")
    p.add_argument("--letzter", type=int, help="letzter Bundesliga-Spieltag der neuen Saison")
    p.add_argument("--zuruecknehmen", action="store_true", help="zuletzt angelegte, leere Saison entfernen")
    p.add_argument("--ohne-webseite", action="store_true")
    a = p.parse_args()
    log = automatik.Bericht(a.system)
    try:
        if a.zuruecknehmen:
            geaendert = zuruecknehmen(a.system, log, a.pruefen)
        else:
            geaendert = anlegen(a.system, log, nur_pruefen=a.pruefen, erzwingen=a.erzwingen, letzter=a.letzter)
        if geaendert and not a.ohne_webseite:
            from scripts import build_site
            build_site.main(build_site.SYSTEMS)
            log("🌐 Webseite neu gebaut")
    finally:
        log.speichern()
    return 0


if __name__ == "__main__":
    sys.exit(main())
