# -*- coding: utf-8 -*-
"""
Live-/Spieler-Aktionen und Abo-Status erkunden (nur lesen, nichts aendern)
=========================================================================

Prueft zwei Dinge:
  1) Liefert die API die einzelnen Aktionen eines Spielers pro Spiel
     (z. B. "Pass in gegnerische Haelfte", "Pass ins letzte Drittel") mit Punkten?
  2) Laesst sich pro Manager der Abo-Status (Amateur / Member / Pro) erkennen?

Aufruf (im Ordner KBL2.0):

    python scripts/live_erkunden.py kbl --spieltag 7
    python scripts/live_erkunden.py kbl --spieltag 7 --liga "Liga 2"

--spieltag  Bundesliga-Spieltag, der schon gespielt ist (oder gerade laeuft)
--liga      Teil des Liganamens oder Liga-ID (Standard: erste Liga des Accounts)

Ergebnis: api_dump/live/  (Rohdaten als JSON + uebersicht.txt + status.txt)
Bitte den Ordner api_dump/live als ZIP schicken. Zugangsdaten/Token werden nicht gespeichert.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from api_erkunden import (Api, zugangsdaten, ligen_finden, name_von,  # noqa: E402
                          speichern, uebersicht_schreiben)

ZIEL = os.path.join("api_dump", "live")
COMP = 1   # Bundesliga


def kurz(d):
    if isinstance(d, dict) and "_fehler" in d:
        return "FEHLER %s %s" % (d["_fehler"], (d.get("_text") or "")[:80])
    if isinstance(d, dict):
        return "ok, Felder: " + ", ".join(list(d)[:15])
    if isinstance(d, list):
        return "ok, Liste mit %d Eintraegen" % len(d)
    return "ok"


def flach(obj, pfad="", out=None, tiefe=0):
    """Alle einfachen Werte als {pfad: wert} (Listen nur 1. Eintrag)."""
    if out is None:
        out = {}
    if tiefe > 5:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            flach(v, pfad + "." + k if pfad else k, out, tiefe + 1)
    elif isinstance(obj, list):
        if obj:
            flach(obj[0], pfad + "[0]", out, tiefe + 1)
    else:
        out[pfad] = obj
    return out


def ohne_token(d):
    if isinstance(d, dict):
        return {k: ("<entfernt>" if k.lower() in ("tkn", "token", "tknex", "pass", "em", "email", "vemail", "emve") else ohne_token(v))
                for k, v in d.items()}
    if isinstance(d, list):
        return [ohne_token(x) for x in d]
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("system", choices=["kbl", "kwbl"])
    ap.add_argument("--spieltag", type=int, required=True)
    ap.add_argument("--liga")
    a = ap.parse_args()
    tag = a.spieltag
    os.makedirs(ZIEL, exist_ok=True)

    api = Api(*zugangsdaten(a.system))
    print("Login ok.")
    speichern(ZIEL, "00_login_ohne_token", ohne_token(api.login_antwort))

    _, ligen = ligen_finden(api)
    lid, lname = ligen[0]
    if a.liga:
        treffer = [(i, n) for i, n in ligen if a.liga == i or a.liga.lower() in n.lower()]
        if not treffer:
            sys.exit("Liga nicht gefunden: %s" % a.liga)
        lid, lname = treffer[0]
    print("Liga: %s (%s), Bundesliga-Spieltag %d\n" % (lname, lid, tag))

    # ------------------------------------------------ 1) Abo-Status
    status = []
    r = api.get("/v4/leagues/%s/ranking?dayNumber=%d" % (lid, tag))
    speichern(ZIEL, "10_ranking", r)
    us = (r.get("us") or []) if isinstance(r, dict) else []
    status.append("Ranking: %d Manager" % len(us))
    # Felder, deren Werte sich zwischen Managern unterscheiden und wenige Auspraegungen haben
    werte = {}
    for u in us:
        for k, v in flach(u).items():
            werte.setdefault(k, []).append(v)
    status.append("\nKandidaten fuer den Status im Ranking (Feld: Werte):")
    for k, vs in sorted(werte.items()):
        verschieden = sorted(set(json.dumps(v, ensure_ascii=False) for v in vs))
        if 1 < len(verschieden) <= 4 or k.lower() in ("pro", "mb", "mbr", "ip", "st", "abo", "sub", "tier"):
            status.append("  %-12s %s" % (k, " | ".join(verschieden)))
    status.append("\nManager einzeln (Name, ID und alle kurzen Felder):")
    for u in us:
        f = {k: v for k, v in flach(u).items() if not isinstance(v, str) or len(v) < 25}
        f.pop("lp[0]", None)
        status.append("  %-22s %s" % (name_von(u), json.dumps(f, ensure_ascii=False)[:300]))

    for u in us[:4]:
        uid = str(u.get("i"))
        for name, pfad in [
            ("dashboard", "/v4/leagues/%s/managers/%s/dashboard" % (lid, uid)),
            ("performance", "/v4/leagues/%s/managers/%s/performance" % (lid, uid)),
            ("profil_v4_users", "/v4/users/%s/profile" % uid),
            ("profil_v4_user", "/v4/user/%s/profile" % uid),
        ]:
            d = api.get(pfad)
            speichern(os.path.join(ZIEL, "manager_" + uid), name, d)
            status.append("  %s %-16s %s" % (uid, name, kurz(d)))
    for name, pfad in [("eigene_einstellungen", "/v4/user/settings"),
                       ("eigenes_profil", "/v4/user/me"),
                       ("liga_me", "/v4/leagues/%s/me" % lid)]:
        d = api.get(pfad)
        speichern(ZIEL, "20_" + name, ohne_token(d))
        status.append("  %-28s %s" % (name, kurz(d)))

    # ------------------------------------------------ 2) Spieler-Aktionen
    et = api.get("/v4/live/eventtypes")
    speichern(ZIEL, "30_eventtypes", et)
    status.append("\nAktionsarten /v4/live/eventtypes: %s" % kurz(et))

    spieler = []
    for u in us[:3]:
        for pid in (u.get("lp") or [])[:3]:
            if pid and str(pid) not in spieler:
                spieler.append(str(pid))
    if not spieler:   # Fallback: Team Center des ersten Managers
        tc = api.get("/v4/leagues/%s/users/%s/teamcenter?dayNumber=%d" % (lid, us[0].get("i"), tag)) if us else {}
        speichern(ZIEL, "31_teamcenter", tc)
        for l in (tc.get("lp") or [] if isinstance(tc, dict) else [])[:6]:
            spieler.append(str(l.get("i") if isinstance(l, dict) else l))
    status.append("Getestete Spieler-IDs: %s" % ", ".join(spieler))

    for pid in spieler[:6]:
        for name, pfad in [
            ("playercenter_comp", "/v4/competitions/%d/playercenter/%s?day=%d" % (COMP, pid, tag)),
            ("playercenter_liga", "/v4/leagues/%s/playercenter/%s?day=%d" % (lid, pid, tag)),
            ("performance_comp", "/v4/competitions/%d/players/%s/performance" % (COMP, pid)),
            ("performance_liga", "/v4/leagues/%s/players/%s/performance" % (lid, pid)),
            ("spieler_liga", "/v4/leagues/%s/players/%s" % (lid, pid)),
        ]:
            d = api.get(pfad)
            speichern(os.path.join(ZIEL, "spieler_" + pid), name, d)
            status.append("  %s %-18s %s" % (pid, name, kurz(d)))

    with open(os.path.join(ZIEL, "status.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(status))
    print("\n".join(status))
    print("\nFeld-Uebersicht: %s" % uebersicht_schreiben(ZIEL))
    print("Fertig. Bitte den Ordner %s als ZIP schicken." % ZIEL)
    print("Hilfreich: kurz dazuschreiben, welchen Status (Amateur/Member/Pro) du selbst und 2-3 der Manager oben haben.")


if __name__ == "__main__":
    main()
