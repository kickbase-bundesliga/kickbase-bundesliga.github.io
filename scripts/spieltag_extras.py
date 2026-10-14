# -*- coding: utf-8 -*-
"""
Zusatzdaten pro Spieltag: Kaderwerte, Aufstellungen und die drei Elfen des Spieltags.

    python scripts/spieltag_extras.py kbl 4        Bundesliga-Spieltag 4 holen
    python scripts/spieltag_extras.py kbl 1-4      Spieltage 1 bis 4 nachholen (aktuelle Saison)

Laeuft automatisch mit, wenn du update.py benutzt (ausser mit --ohne-extras).

Was pro Spieltag gespeichert wird (league_systems/<system>/extras/<Saison>.json):
  - je Manager: Liga, Spieltagspunkte, Kaderwert an diesem Spieltag, Startelf (Spieler-IDs)
  - je aufgestelltem Spieler: Punkte an diesem Spieltag
  - drei Elfen:
      winner = Startelf des Managers mit den meisten Spieltagspunkten ueber alle Ligen
      most   = die am haeufigsten aufgestellten Spieler (in der besten erlaubten Formation)
      top    = die punktbesten aufgestellten Spieler (in der besten erlaubten Formation)
Spielerstammdaten (Name, Position, Verein) werden in extras/spieler.json zwischengespeichert,
damit sie nur einmal abgefragt werden muessen.

Nur lesende API-Abfragen. Python 3.7, nur Standardbibliothek.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.append("./")
from scripts import utils

BASIS = "https://api.kickbase.com/v4"
PAUSE = 0.25

# In Kickbase erlaubte Formationen (Abwehr-Mittelfeld-Sturm)
FORMATIONEN = ["3-4-3", "3-5-2", "3-6-1", "4-2-4", "4-3-3", "4-4-2", "4-5-1", "5-2-3", "5-3-2", "5-4-1"]
# Kickbase-Positionen: 1 Tor, 2 Abwehr, 3 Mittelfeld, 4 Sturm


# ---------------------------------------------------------------- API

class Api:
    def __init__(self, system):
        # Zugangsdaten aus config/<system>.txt oder aus GitHub Secrets (siehe utils.zugangsdaten)
        email, passwort, _ = utils.zugangsdaten(system)
        zeilen = [email, passwort]
        self.token = None
        self.anfragen = 0
        antwort = self._anfrage("POST", "/user/login",
                                {"em": zeilen[0], "pass": zeilen[1], "loy": False, "rep": {}})
        self.login_antwort = antwort if isinstance(antwort, dict) else {}
        self.token = antwort.get("tkn") if isinstance(antwort, dict) else None
        if not self.token:
            raise RuntimeError("Login fehlgeschlagen: %s" % json.dumps(antwort)[:300])

    def _anfrage(self, methode, pfad, body=None, versuche=3):
        daten = json.dumps(body).encode("utf-8") if body is not None else None
        for versuch in range(versuche):
            req = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
            req.add_header("Accept", "application/json")
            req.add_header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
            if daten is not None:
                req.add_header("Content-Type", "application/json")
            if self.token:
                req.add_header("Authorization", "Bearer " + self.token)
            self.anfragen += 1
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    text = r.read().decode("utf-8")
                time.sleep(PAUSE)
                return json.loads(text) if text else {}
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and versuch < versuche - 1:
                    time.sleep(3 * (versuch + 1))
                    continue
                return {"_fehler": e.code}
            except Exception as e:
                if versuch < versuche - 1:
                    time.sleep(3)
                    continue
                return {"_fehler": str(e)}
        return {"_fehler": "unbekannt"}

    def get(self, pfad):
        return self._anfrage("GET", pfad)


# ---------------------------------------------------------------- Elfen

def beste_elf(kandidaten, wert, nebenwert):
    """kandidaten: {pid: {"pos": 1-4, ...}}. Waehlt die erlaubte Formation mit der hoechsten Summe.
    Gibt (formation, [pid, ...]) zurueck, Reihenfolge Tor, Abwehr, Mittelfeld, Sturm."""
    nach_pos = {1: [], 2: [], 3: [], 4: []}
    for pid, k in kandidaten.items():
        if k.get("pos") in nach_pos:
            nach_pos[k["pos"]].append(pid)
    for pos in nach_pos:
        nach_pos[pos].sort(key=lambda p: (wert(p), nebenwert(p)), reverse=True)
    if not nach_pos[1]:
        return None, []
    beste = (None, None, [])
    for f in FORMATIONEN:
        d, m, s = [int(x) for x in f.split("-")]
        if len(nach_pos[2]) < d or len(nach_pos[3]) < m or len(nach_pos[4]) < s:
            continue
        elf = nach_pos[1][:1] + nach_pos[2][:d] + nach_pos[3][:m] + nach_pos[4][:s]
        summe = (sum(wert(p) for p in elf), sum(nebenwert(p) for p in elf))
        if beste[1] is None or summe > beste[1]:
            beste = (f, summe, elf)
    return beste[0], beste[2]


def formation_von(elf, spieler):
    zaehl = {2: 0, 3: 0, 4: 0}
    for pid in elf:
        pos = spieler.get(pid, {}).get("pos")
        if pos in zaehl:
            zaehl[pos] += 1
    return "%d-%d-%d" % (zaehl[2], zaehl[3], zaehl[4])


def sortiert(elf, spieler):
    return sorted(elf, key=lambda p: spieler.get(p, {}).get("pos") or 9)


# ---------------------------------------------------------------- Abruf

def lade_json(pfad, standard):
    if os.path.exists(pfad):
        with open(pfad, encoding="utf8") as f:
            return json.load(f)
    return standard


def schreibe_json(pfad, daten):
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    tmp = pfad + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(daten, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, pfad)


def ligen_des_systems(api, system, config):
    """Liga-IDs aller Ligen dieses Systems aus der Liga-Auswahl des Admin-Accounts."""
    gueltig = set()
    try:
        gueltig = set(utils.get_valid_league_names(system))
    except Exception:
        pass
    if not gueltig:
        for lc in config["leagues"]:
            gueltig.update(lc["names"])
    auswahl = api.get("/leagues/selection")
    ligen = []

    def suchen(obj):
        if isinstance(obj, list):
            for x in obj:
                suchen(x)
        elif isinstance(obj, dict):
            name = obj.get("n") or obj.get("lnm") or obj.get("name")
            if "i" in obj and name in gueltig:
                ligen.append((str(obj["i"]), name))
            for v in obj.values():
                if isinstance(v, (list, dict)):
                    suchen(v)

    suchen(auswahl)
    return sorted(set(ligen), key=lambda x: x[1])


def hole_spieltag(api, system, bl_md, ligen, admin, spieler, log=print):
    """Holt einen Bundesliga-Spieltag fuer alle Ligen. Gibt den Datensatz fuer diesen Spieltag zurueck."""
    manager = {}
    for lid, lname in ligen:
        r = api.get("/leagues/%s/ranking?dayNumber=%d" % (lid, bl_md))
        if not isinstance(r, dict) or "_fehler" in r:
            log("   ⚠️  %s: Tabelle nicht abrufbar (%s)" % (lname, r.get("_fehler") if isinstance(r, dict) else r))
            continue
        for u in r.get("us", []):
            uid = str(u.get("i"))
            if uid == admin:
                continue
            manager[uid] = {
                "l": lname, "lid": lid, "n": u.get("n"),
                "mdp": u.get("mdp") or 0,
                "tv": int(u.get("tv") or 0),
                "lp": [str(p) for p in (u.get("lp") or [])],
            }
    if not manager:
        return None
    if not any(m["mdp"] for m in manager.values()):
        return {"leer": True}

    # Punkte der aufgestellten Spieler: Team Center liefert sie fuer die Startelf eines Managers.
    # Spielerpunkte sind in allen Ligen gleich -> nur so viele Team Center abfragen, bis alle abgedeckt sind.
    alle = set(p for m in manager.values() for p in m["lp"])
    punkte = {}
    reihenfolge = sorted(manager, key=lambda u: manager[u]["mdp"], reverse=True)
    tc_anfragen = 0
    for uid in reihenfolge:
        m = manager[uid]
        if not m["lp"] or all(p in punkte for p in m["lp"]):
            continue
        tc = api.get("/leagues/%s/users/%s/teamcenter?dayNumber=%d" % (m["lid"], uid, bl_md))
        tc_anfragen += 1
        for s in (tc.get("lp") or []) if isinstance(tc, dict) else []:
            pid = str(s.get("i"))
            punkte[pid] = s.get("p") or 0
            if pid not in spieler and s.get("n"):
                spieler[pid] = {"n": s.get("n"), "tid": str(s.get("tid") or "")}
        if len(punkte) >= len(alle):
            break

    # Fehlende Stammdaten (Position) einmalig nachladen und zwischenspeichern
    erste_liga = ligen[0][0]
    neu = 0
    for pid in alle:
        if spieler.get(pid, {}).get("pos"):
            continue
        d = api.get("/leagues/%s/players/%s" % (erste_liga, pid))
        if isinstance(d, dict) and "_fehler" not in d:
            spieler[pid] = {"n": d.get("ln") or spieler.get(pid, {}).get("n") or pid,
                            "fn": d.get("fn") or "", "pos": d.get("pos"),
                            "tid": str(d.get("tid") or ""), "tn": d.get("tn") or ""}
            neu += 1

    # Haeufigkeit: in wie vielen Aufstellungen (= Ligen) stand der Spieler
    anzahl = {}
    for m in manager.values():
        for p in m["lp"]:
            anzahl[p] = anzahl.get(p, 0) + 1

    kand = {p: spieler.get(p, {}) for p in alle}
    pkt = lambda p: punkte.get(p, 0) or 0
    anz = lambda p: anzahl.get(p, 0)

    sieger = max(manager, key=lambda u: (manager[u]["mdp"], u))
    s_elf = sortiert(manager[sieger]["lp"], spieler)
    f_most, most = beste_elf(kand, anz, pkt)
    f_top, top = beste_elf(kand, pkt, anz)

    log("   ✅ %d Manager, %d Spieler, %d Team-Center-Abfragen, %d neue Spieler" %
        (len(manager), len(alle), tc_anfragen, neu))

    return {
        "bl": bl_md,
        "managers": {u: {"l": m["l"], "mdp": m["mdp"], "tv": m["tv"], "lp": m["lp"]} for u, m in manager.items()},
        "points": {p: punkte[p] for p in sorted(punkte)},
        "elfs": {
            "winner": {"id": sieger, "f": formation_von(s_elf, spieler), "p": s_elf},
            "most": {"f": f_most, "p": most},
            "top": {"f": f_top, "p": top},
        },
    }


def run(system, bl_spieltage, log=print):
    """bl_spieltage: Liste von Bundesliga-Spieltagen der aktuellen Saison."""
    config = utils.read_json("config/%s" % system)
    season = utils.get_current_season(system)
    admin = str(config.get("admin_id"))
    ordner = os.path.join("league_systems", system, "extras")
    spieler_pfad = os.path.join(ordner, "spieler.json")
    saison_pfad = os.path.join(ordner, "%s.json" % season["name"])
    spieler = lade_json(spieler_pfad, {})
    saison = lade_json(saison_pfad, {"season": season["name"], "md": {}})

    api = Api(system)
    ligen = ligen_des_systems(api, system, config)
    if not ligen:
        log("   ⚠️  Keine Ligen dieses Systems im Account gefunden.")
        return False
    log("   %d Ligen" % len(ligen))

    ok = False
    for bl in bl_spieltage:
        md = utils.get_kbl_matchday(bl, season["name"], system)
        log("   Bundesliga-Spieltag %d (= %s-Spieltag %s)" % (bl, system.upper(), md))
        daten = hole_spieltag(api, system, bl, ligen, admin, spieler, log)
        if daten is None:
            log("   ⚠️  Keine Daten fuer diesen Spieltag.")
            continue
        if daten.get("leer"):
            log("   ⚠️  Alle Spieltagspunkte sind 0 - Spieltag noch nicht gespielt? Nicht gespeichert.")
            continue
        saison["md"][str(md)] = daten
        schreibe_json(saison_pfad, saison)
        schreibe_json(spieler_pfad, spieler)
        ok = True
    log("   %d API-Anfragen" % api.anfragen)
    return ok


def spieltage_lesen(text):
    if "-" in text:
        a, b = text.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(text)]


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1].lower() not in utils.alle_systeme():
        sys.exit("Aufruf: python scripts/spieltag_extras.py kbl 4   oder   python scripts/spieltag_extras.py kbl 1-4")
    run(sys.argv[1].lower(), spieltage_lesen(sys.argv[2]))
