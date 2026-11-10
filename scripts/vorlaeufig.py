# -*- coding: utf-8 -*-
"""
Vorlaeufiger Zwischenstand des laufenden Spieltags (vor der Kickbase-Abrechnung).

Sobald vom naechsten noch nicht eingespielten Spieltag mindestens ein Spiel beendet ist, holt der
Spieltags-Lauf (automatik.py) die Live-Spieltagspunkte aller Manager ueber
/leagues/<id>/ranking?dayNumber=<Spieltag> und legt sie in
league_systems/<system>/vorlaeufig.json ab. Die Datenbank bleibt unangetastet.

build_site.py traegt die Punkte nur in die Tabellen der Webseite ein (season_<S>.json,
"provisional_md") - die Seite markiert den Spieltag als "vorlaeufig". KBL-Score, Statistik,
Hall of Fame, Pokal und Tabellenbilder sehen den Zwischenstand nicht.

Wird der Spieltag nach der Abrechnung regulaer eingespielt, loescht automatik.py die Datei.
In config/<system>.json abschaltbar: "automatik": {"vorlaeufig": false}.
"""
import json
import os
from datetime import timedelta

SPIELDAUER = timedelta(hours=2)        # Anstoss + 2 h = Spiel beendet


def pfad(system):
    return os.path.join("league_systems", system, "vorlaeufig.json")


def lesen(system):
    p = pfad(system)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def loeschen(system, log=print, bis_spieltag=None):
    """Zwischenstand entfernen (ganz oder wenn er zu einem schon eingespielten Spieltag gehoert)."""
    v = lesen(system)
    if v is None:
        return False
    if bis_spieltag is not None and int(v.get("bl_spieltag", 0)) > bis_spieltag:
        return False
    os.remove(pfad(system))
    log("🧹 Vorlaeufiger Stand von Spieltag %s entfernt (jetzt endgueltig eingespielt)." % v.get("bl_spieltag"))
    return True


def kandidat(plan, ab_tag, letzter_tag, now):
    """Naechster nicht eingespielter Spieltag, von dem mindestens ein Spiel beendet ist -> Nr oder None."""
    for tag in range(ab_tag, letzter_tag + 1):
        zeiten = plan.get(tag) or []
        if not zeiten:
            return None
        if any(z + SPIELDAUER <= now for z in zeiten):
            return tag
        return None
    return None


def holen(system, saison, bl_tag, now, log=print, pruefen=False):
    """Live-Spieltagspunkte holen und speichern. -> True, wenn sich der Stand geaendert hat."""
    from scripts import utils
    from scripts.spieltag_extras import Api, ligen_des_systems
    config = utils.read_json("config/%s" % system)
    if (config.get("automatik") or {}).get("vorlaeufig") is False:
        return False
    md = utils.get_kbl_matchday(bl_tag, saison["name"], system)
    log("⏱️  Vorlaeufiger Stand Spieltag %d (= %s-Spieltag %s)" % (bl_tag, system.upper(), md))
    if pruefen:
        log("   (nur Pruefung - nichts geholt)")
        return False
    admin = str(config.get("admin_id"))
    api = Api(system)
    ligen = ligen_des_systems(api, system, config)
    punkte, ok = {}, 0
    for lid, lname in ligen:
        r = api.get("/leagues/%s/ranking?dayNumber=%d" % (lid, bl_tag))
        if not isinstance(r, dict) or "_fehler" in r:
            log("   ⚠️  %s: keine Daten (%s)" % (lname, (r or {}).get("_fehler") if isinstance(r, dict) else r))
            continue
        ok += 1
        for u in r.get("us") or []:
            uid = str(u.get("i"))
            if uid == admin or u.get("adm"):
                continue
            punkte[uid] = int(u.get("mdp") or 0)
    if not ok:
        log("   ⚠️  Keine Liga lieferte Daten - Zwischenstand nicht aktualisiert.")
        return False
    alt = lesen(system) or {}
    neu = {"saison": saison["name"], "bl_spieltag": bl_tag, "spieltag": md,
           "abgerufen": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "punkte": punkte}
    geaendert = alt.get("punkte") != punkte or alt.get("bl_spieltag") != bl_tag
    with open(pfad(system), "w", encoding="utf-8") as f:
        json.dump(neu, f, ensure_ascii=False, indent=1)
        f.write("\n")
    log("   %d Ligen, %d Manager mit Live-Punkten%s" % (ok, sum(1 for p in punkte.values() if p),
                                                         "" if geaendert else " (unveraendert)"))
    return geaendert
