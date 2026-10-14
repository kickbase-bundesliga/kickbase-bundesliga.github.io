"""
Erzeugt die Webseite aus der lokalen Datenbank.

    python scripts/build_site.py            -> baut docs/ (alle Ligasysteme)
    python scripts/build_site.py kbl        -> nur KBL

Ergebnis: Ordner docs/ mit index.html und data/*.json. Den Ordner kann man direkt
online veroeffentlichen (macht der GitHub-Workflow "Webseite" automatisch)
oder lokal ansehen mit:  python -m http.server -d docs  ->  http://localhost:8000
"""
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.append("./")
from scripts import utils

try:
    SYSTEMS = utils.alle_systeme()      # alle config/<system>.json
except Exception:
    SYSTEMS = ["kbl", "kwbl"]
OUT_DIR = "docs"
TEMPLATE = "website/index.html"
CUP_ROUNDS = [0, 2, 4, 8, 16, 32]


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------

def short_league(name):
    """'KBL - Liga 4A' -> 'Liga 4A'"""
    if not name:
        return None
    return name.split(" - ", 1)[1] if " - " in name else name


def load_live_draw(system):
    """league_systems/<system>/cup/live_auslosung.json (von pokal.py) oder None."""
    path = f"league_systems/{system}/cup/live_auslosung.json"
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf8") as fp:
        return json.load(fp)


def load_cups(system):
    cups = {}
    folder = f"league_systems/{system}/cup"
    prefix = f"{system.upper()}Cup_Database_"
    if not os.path.isdir(folder):
        return cups
    for fn in os.listdir(folder):
        if fn.startswith(prefix) and fn.endswith(".json") and "_backup_" not in fn:
            season = fn[len(prefix):-5]
            with open(os.path.join(folder, fn), encoding="utf8") as fp:
                cups[season] = json.load(fp)
    return cups


def normalize_results(results):
    """Ergebnisse sind meist [[[id,p],[id,p]], ...]; in einer Datei fehlt eine Ebene."""
    if not results:
        return []
    if results and isinstance(results[0], list) and results[0] and not isinstance(results[0][0], list):
        return [results]
    return results


def cup_round_reached(cup, manager_id):
    """Wie kbl_score.get_cup_round: 0 = Sieger, 2 = Finale verloren, ... 32 = frueh raus/nicht dabei."""
    try:
        for rnd, val in [("2", 0), ("4", 2), ("8", 4), ("16", 8), ("32", 16)]:
            if manager_id in cup[rnd]["Winners"]:
                return val
    except (KeyError, TypeError):
        pass
    return 32


def league_score(place, league, config):
    # bewusst identisch zu kbl_score.calculate_score (nur Ligen aus der Config zaehlen)
    if place is None:
        return 0
    if place == 18:
        place = 17
    for lc in config["leagues"]:
        if league in lc["names"]:
            scores = lc.get("kbl_score", [])
            return scores[place - 1] if 1 <= place <= len(scores) else 0
    return 0


def cup_score(cup_round, config):
    scores = config.get("cup_scores", [])
    if cup_round in CUP_ROUNDS:
        i = CUP_ROUNDS.index(cup_round)
        if i < len(scores):
            return scores[i]
    return 0


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def build_system(system):
    config = utils.read_json(f"config/{system}")
    database = utils.read_json(f"league_systems/{system}/databases/{system}_database")
    cups = load_cups(system)
    live = load_live_draw(system)
    # Live-Auslosung: die frisch geloste Runde bleibt in der Pokal-Ansicht verborgen, bis die
    # Webseite sie gezogen hat (die Seite blendet sie danach aus auslosung.json ein).
    hidden_round = None
    if live and live.get("status") == "gezogen":
        r = cups.get(live.get("saison"), {}).get(str(live.get("runde")))
        if r is not None and not r.get("Results"):
            hidden_round = (live["saison"], str(live["runde"]))
    admin = str(config["admin_id"])
    prefix = config["league_system_shortcut"]

    seasons_cfg = sorted(config["seasons"], key=lambda s: s["name"])   # alt -> neu
    season_names = [s["name"] for s in seasons_cfg]
    current = season_names[-1]
    # Erinnerungs-Saisons (z. B. Quali 2019B): auf der Seite sichtbar, aber ohne Titel und KBL-Score
    quali = set(s["name"] for s in seasons_cfg if s.get("quali"))
    score_seasons = [s for s in season_names if s not in quali]

    league_level = {}
    league_cfg = {}
    for lc in config["leagues"]:
        for n in lc["names"]:
            league_level[n] = int(lc["level"])
            league_cfg[n] = lc

    managers = {mid: m for mid, m in database.items() if str(mid) != admin}

    # Ligen, die es frueher gab, aber nicht mehr in der Config stehen (z.B. "KWBL - Liga 4D"):
    # Level aus dem Namen ableiten und Zonen der gleichen Ebene verwenden.
    import re
    level_cfg = {int(lc["level"]): lc for lc in config["leagues"]}
    for m in database.values():
        for k, d in m.items():
            if k.startswith("20") and isinstance(d, dict) and d.get("League") and d["League"] not in league_level:
                hit = re.search(r"Liga\s*(\d+)", d["League"]) or re.search(r"\b[A-Z]+\s*(\d+)\s*-", d["League"])
                if hit:
                    lv = int(hit.group(1))
                    league_level[d["League"]] = lv
                    if k in quali:
                        league_cfg[d["League"]] = {"distribution": [], "kbl_score": []}   # keine Farbzonen
                    else:
                        league_cfg[d["League"]] = level_cfg.get(lv, {"distribution": [], "kbl_score": []})

    gaps = read_gaps(system)            # {Saison: [Ebenen ohne Tabellen]}

    def season_entry(m, s):
        d = m.get(s)
        if isinstance(d, dict) and d.get("League") and d["League"] in league_level:
            return d
        return None

    # ---------------- Saisons ----------------
    out_dir = os.path.join(OUT_DIR, "data", system)
    os.makedirs(out_dir, exist_ok=True)
    seasons_meta = []
    for scfg in seasons_cfg:
        s = scfg["name"]
        leagues = {}
        last_md = 0
        for mid, m in managers.items():
            d = season_entry(m, s)
            if not d:
                continue
            md = [p or 0 for p in (d.get("MdPoints") or [])]
            filled = [i for i, p in enumerate(md) if p]
            if filled:
                last_md = max(last_md, filled[-1])
            corr = utils.get_corrections(d)
            row = {"id": mid, "place": d.get("Place"), "points": d.get("Points"), "md": md}
            if corr:
                row["corr"] = {str(k): v for k, v in corr.items()}
            leagues.setdefault(d["League"], []).append(row)

        if not leagues:
            continue
        # Ligen nach Level, dann Name
        league_list = []
        for name in sorted(leagues, key=lambda n: (league_level[n], n)):
            lc = league_cfg[name]
            league_list.append({
                "name": name,
                "short": short_league(name),
                "level": league_level[name],
                "zones": lc.get("distribution", []),
                "rows": leagues[name],
            })
        data = {
            "season": s,
            "current": s == current,
            "quali": s in quali,
            "first_matchday": int(scfg["first_matchday"]),
            "matchdays": int(scfg["matchday_number"]),
            "last_md": last_md,
            "leagues": league_list,
        }
        with open(os.path.join(out_dir, f"season_{s}.json"), "w", encoding="utf8") as fp:
            json.dump(data, fp, ensure_ascii=False, separators=(",", ":"))
        seasons_meta.append({
            "name": s,
            "current": s == current,
            "quali": s in quali,
            "last_md": last_md,
            "matchdays": int(scfg["matchday_number"]),
            "first_matchday": int(scfg["first_matchday"]),
            "managers": sum(len(v) for v in leagues.values()),
            # Mindestzahl laut Platzierungen (falls in alten Saisons Manager in der DB fehlen)
            "min_managers": sum(max(len(v), max([r["place"] or 0 for r in v] or [0])) for v in leagues.values()),
            "levels": len(set(league_level[n] for n in leagues)),
            "leagues": [l["short"] for l in league_list],
            "has_cup": s in cups,
            **({"gaps": gaps[s]} if s in gaps else {}),
        })

    # ---------------- Pokal ----------------
    cup_meta = []
    for s, cup in sorted(cups.items()):
        rounds = []
        for rnd in sorted(cup, key=int, reverse=True):
            if (s, rnd) == hidden_round:
                continue
            r = cup[rnd]
            results = normalize_results(r.get("Results"))
            res_map = {}
            for (a, pa), (b, pb) in results:
                res_map[(str(a), str(b))] = (pa, pb)
            matches = []
            for a, b in r.get("Matchups", []):
                a, b = str(a), str(b)
                pa, pb = res_map.get((a, b), (None, None))
                w = None
                winners = [str(x) for x in r.get("Winners", [])]
                if a in winners:
                    w = a
                elif b in winners:
                    w = b
                matches.append({"a": a, "b": b, "pa": pa, "pb": pb, "w": w})
            rounds.append({"size": int(rnd), "matches": matches, "done": bool(r.get("Winners"))})
        if not rounds:
            continue
        final = cup.get("2", {})
        winner = (final.get("Winners") or [None])[0]
        runner_up = None
        score = None
        if winner and final.get("Matchups"):
            a, b = [str(x) for x in final["Matchups"][0]]
            runner_up = b if a == str(winner) else a
            fr = normalize_results(final.get("Results"))
            if fr:
                (ia, pa), (ib, pb) = fr[0]
                score = [pa, pb] if str(ia) == str(winner) else [pb, pa]
        # Liga der Teilnehmer in dieser Saison
        part_league = {}
        for rd in rounds:
            for mt in rd["matches"]:
                for x in (mt["a"], mt["b"]):
                    if x != "Freilos" and x not in part_league:
                        d = season_entry(managers.get(x, {}), s)
                        part_league[x] = short_league(d["League"]) if d else None
        with open(os.path.join(out_dir, f"cup_{s}.json"), "w", encoding="utf8") as fp:
            json.dump({"season": s, "rounds": rounds, "leagues": part_league}, fp,
                      ensure_ascii=False, separators=(",", ":"))
        cup_meta.append({
            "season": s,
            "winner": str(winner) if winner else None,
            "runner_up": runner_up,
            "score": score,
            "participants": len(part_league),
            "current_round": rounds[-1]["size"] if rounds else None,
            "finished": bool(winner),
        })

    # ---------------- Manager, Titel, KBL-Score ----------------
    finished_seasons = [s["name"] for s in seasons_meta if not s["current"]]
    level1 = [n for n, lv in league_level.items() if lv == 1]
    mgr_out = {}
    champions = []
    score_rows = []
    score_mismatch = 0
    for mid, m in managers.items():
        career = []
        titles = {"gold": [], "silver": [], "bronze": [], "cup": [], "cup_final": []}
        score_total = 0
        per_season = {}
        for s in season_names:
            d = season_entry(m, s)
            cup = cups.get(s)
            cr = cup_round_reached(cup, mid) if cup else 32
            if d:
                ls = 0 if s in quali else league_score(d.get("Place"), d["League"], config)
                cs = 0 if s in quali else cup_score(cr, config)
                score_total += ls + cs
                if s not in quali:
                    per_season[s] = [ls, cs]
                career.append({
                    "s": s,
                    "league": short_league(d["League"]),
                    "level": league_level[d["League"]],
                    "place": d.get("Place"),
                    "points": d.get("Points"),
                    "cup": cr if cup and mid in cups_participants(cup) else None,
                    "score": ls + cs,
                    **({"q": 1} if s in quali else {}),
                })
                if s in finished_seasons and s not in quali and d["League"] in level1 and d.get("Place") in (1, 2, 3):
                    key = {1: "gold", 2: "silver", 3: "bronze"}[d["Place"]]
                    titles[key].append(s)
            if cup and cr == 0:
                titles["cup"].append(s)
            elif cup and cr == 2:
                titles["cup_final"].append(s)
        # Saisons, in denen der Manager vermutlich in einer Liga ohne Tabelle spielte:
        # kein Eintrag, aber direkt davor und danach in der Ebene darueber oder in dieser Ebene
        mgaps = []
        for s, lvls in gaps.items():
            if s not in season_names or season_entry(m, s):
                continue
            i = season_names.index(s)
            if i == 0 or i + 1 >= len(season_names):
                continue
            a, b = season_entry(m, season_names[i - 1]), season_entry(m, season_names[i + 1])
            for lv in lvls:
                if a and b and league_level[a["League"]] >= lv - 1 and league_level[b["League"]] >= lv - 1:
                    mgaps.append({"s": s, "level": lv})
                    break
        stored = (m.get("Info") or {}).get("KBL Score")
        if stored is not None and stored != score_total:
            score_mismatch += 1
        info = m.get("Info") or {}
        mgr_out[mid] = {
            "n": (m.get("Username") or "?").strip(),
            "league": short_league(info.get("League")),
            "score": score_total,
            "career": career,
            "titles": {k: v for k, v in titles.items() if v},
            **({"gaps": mgaps} if mgaps else {}),
        }
        if score_total:
            score_rows.append({"id": mid, "total": score_total, "seasons": per_season})

    # Meistertafel
    for s in finished_seasons:
        if s in quali:
            continue
        podium = {}
        for mid, m in managers.items():
            d = season_entry(m, s)
            if d and d["League"] in level1 and d.get("Place") in (1, 2, 3):
                podium[d["Place"]] = {"id": mid, "points": d.get("Points")}
        if podium:
            champions.append({"season": s, "podium": [podium.get(i) for i in (1, 2, 3)]})

    score_rows.sort(key=lambda r: r["total"], reverse=True)

    # ---------------- Spieltag-Extras (Kaderwerte, Aufstellungen, Elfen) ----------------
    extras_seasons = export_extras(system, out_dir)

    index = {
        "system": system,
        "name": config["league_system_name"],
        "short": prefix,
        "generated": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "current": current,
        "seasons": list(reversed(seasons_meta)),
        "cup_scores": config["cup_scores"],
        "managers": mgr_out,
        "champions": list(reversed(champions)),
        "cups": list(reversed(cup_meta)),
        "kbl_score": {"seasons": score_seasons, "rows": score_rows},
        "extras": extras_seasons,
        "structure": [{
            "level": int(lc["level"]),
            "leagues": [short_league(n) for n in lc["names"]],
            "score_first": (lc.get("kbl_score") or [0])[0],
            "cup_factor": lc.get("cup_factor"),
            "zones": lc.get("distribution", []),
        } for lc in sorted(config["leagues"], key=lambda l: int(l["level"]))],
        "info": info_html(system),
        "gaps": [{"s": s, "levels": lv} for s, lv in sorted(gaps.items())],
    }
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf8") as fp:
        json.dump(index, fp, ensure_ascii=False, separators=(",", ":"))
    print(f"✅ {prefix}: {len(seasons_meta)} Saisons, {len(cup_meta)} Pokale, {len(mgr_out)} Manager exportiert."
          + (f" ({score_mismatch} KBL-Scores weichen vom gespeicherten Wert ab - kbl_score neu laufen lassen)" if score_mismatch else ""))
    # Logo fuer die Kopfleiste (quadratisches Zeichen), falls vorhanden
    icon_src = f"league_systems/{system}/logo_icon.png"
    has_icon = os.path.exists(icon_src)
    if has_icon:
        shutil.copy(icon_src, os.path.join(out_dir, "logo_icon.png"))
    entry = {"id": system, "short": prefix, "name": config["league_system_name"], "icon": has_icon}
    draw_path = os.path.join(out_dir, "auslosung.json")
    if live:
        draw = {"season": live["saison"], "round": live["runde"], "start": live["start"],
                "sec": live.get("sekunden", 5), "n": live.get("teilnehmer"), "byes": live.get("freilose", 0),
                "first": bool(live.get("erste_runde")), "status": live["status"], "pairs": None}
        if live["status"] == "gezogen":
            r = cups.get(live["saison"], {}).get(str(live["runde"]), {})
            people = {}
            # Ersatz aus der Teilnehmerliste (neue Manager stehen evtl. noch nicht in der Datenbank)
            csv_people = {}
            csv_path = f"league_systems/{system}/cup/{prefix}Cup_Participants_{live['saison']}.csv"
            if os.path.exists(csv_path):
                import csv
                with open(csv_path, newline="", encoding="utf8") as fp:
                    for row in list(csv.reader(fp))[1:]:
                        if len(row) >= 4:
                            lg = row[3].strip()
                            if lg.upper().startswith(prefix + " "):
                                lg = "Liga " + lg[len(prefix) + 1:]
                            csv_people[row[1].strip()] = {"n": row[2].strip(), "l": lg}
            for pair in r.get("Matchups", []):
                for x in pair:
                    x = str(x)
                    if x == "Freilos" or x in people:
                        continue
                    m = managers.get(x, {})
                    d = season_entry(m, live["saison"])
                    alt = csv_people.get(x, {})
                    people[x] = {"n": m.get("Username") or alt.get("n") or ("ID " + x),
                                 "l": short_league(d["League"]) if d else alt.get("l", "")}
            draw["pairs"] = [[str(a), str(b)] for a, b in r.get("Matchups", [])]
            draw["people"] = people
        with open(draw_path, "w", encoding="utf8") as fp:
            json.dump(draw, fp, ensure_ascii=False, separators=(",", ":"))
        entry["draw"] = {k: draw[k] for k in ("season", "round", "start", "sec", "n", "byes", "first", "status")}
    elif os.path.exists(draw_path):
        os.remove(draw_path)
    return entry


def read_gaps(system):
    """config/<system>_luecken.txt: Ligen, fuer die es keine Tabellen mehr gibt.
    Je Zeile  Saison; Ebene   z. B.  2023B; 6   (// = Kommentar). Fehlt die Datei: keine Luecken."""
    path = f"config/{system}_luecken.txt"
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig") as fp:
        for raw in fp:
            line = raw.split("//")[0].strip()
            if not line:
                continue
            parts = [x.strip() for x in line.replace(",", ";").split(";")]
            try:
                out.setdefault(parts[0], []).append(int(parts[1]))
            except (IndexError, ValueError):
                print(f"   Hinweis: Zeile in {path} nicht verstanden: {raw.strip()}")
    return out


def _inline(text):
    """Text sicher machen, dann **fett** und [Linktext](https://...) erlauben."""
    import html
    import re
    t = html.escape(text, quote=True)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)",
               r'<a href="\2" target="_blank" rel="noopener">\1</a>', t)
    return t


def info_html(system):
    """Liest config/<system>_info.txt (frei bearbeitbar) und macht daraus HTML.
    Format:  # Ueberschrift   |  ## Zwischenueberschrift  |  - Aufzaehlungspunkt  |  leere Zeile = neuer Absatz
             **fett**  |  [Linktext](https://...)
    Fehlt die Datei, bleibt der Bereich auf der Webseite einfach weg."""
    path = f"config/{system}_info.txt"
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as fp:
        lines = fp.read().splitlines()
    sections, cur, para, items = [], None, [], []

    def flush():
        if cur is None:
            return
        if para:
            cur["html"] += "<p>" + " ".join(_inline(x) for x in para) + "</p>"
            para.clear()
        if items:
            cur["html"] += "<ul>" + "".join("<li>" + _inline(x) + "</li>" for x in items) + "</ul>"
            items.clear()

    for raw in lines:
        line = raw.strip()
        if line.startswith("//"):
            continue  # Kommentarzeile, erscheint nicht auf der Seite
        if line.startswith("# "):
            flush()
            cur = {"title": line[2:].strip(), "html": ""}
            sections.append(cur)
        elif cur is None:
            continue
        elif line.startswith("## "):
            flush()
            cur["html"] += "<h3>" + _inline(line[3:].strip()) + "</h3>"
        elif line == "{{auf-abstieg}}":
            # Platzhalter: hier zeichnet die Webseite das Auf-/Abstiegs-Schaubild aus der Config
            flush()
            cur["html"] += '<div data-slot="aufabstieg"></div>'
        elif line.startswith("- "):
            if para:
                flush()
            items.append(line[2:].strip())
        elif not line:
            flush()
        else:
            if items:
                flush()
            para.append(line)
    flush()
    return [s for s in sections if s["html"]]


def export_extras(system, out_dir):
    """Kopiert league_systems/<system>/extras/<Saison>.json fuer die Webseite (mit Spielernamen).
    Gibt die Saisons mit Daten zurueck (neueste zuerst)."""
    folder = f"league_systems/{system}/extras"
    if not os.path.isdir(folder):
        return []
    players_path = os.path.join(folder, "spieler.json")
    players = {}
    if os.path.exists(players_path):
        with open(players_path, encoding="utf8") as fp:
            players = json.load(fp)
    seasons = []
    for fn in sorted(os.listdir(folder)):
        if not fn.endswith(".json") or fn == "spieler.json":
            continue
        with open(os.path.join(folder, fn), encoding="utf8") as fp:
            data = json.load(fp)
        if not data.get("md"):
            continue
        used = set()
        mds = {}
        for md, d in data["md"].items():
            for m in d["managers"].values():
                used.update(m["lp"])
            mds[md] = {
                "bl": d.get("bl"),
                "m": {uid: [short_league(m["l"]), m["mdp"], m["tv"], m["lp"]] for uid, m in d["managers"].items()},
                "pts": d.get("points", {}),
                "elfs": d.get("elfs", {}),
            }
        pl = {}
        for pid in used:
            p = players.get(pid, {})
            pl[pid] = [p.get("n") or pid, p.get("pos") or 0, p.get("tn") or ""]
        season = data.get("season") or fn[:-5]
        with open(os.path.join(out_dir, f"extras_{season}.json"), "w", encoding="utf8") as fp:
            json.dump({"season": season, "md": mds, "players": pl}, fp, ensure_ascii=False, separators=(",", ":"))
        seasons.append(season)
    return sorted(seasons, reverse=True)


_participants_cache = {}


def cups_participants(cup):
    key = id(cup)
    if key not in _participants_cache:
        ids = set()
        for r in cup.values():
            for a, b in r.get("Matchups", []):
                ids.update([str(a), str(b)])
        ids.discard("Freilos")
        _participants_cache[key] = ids
    return _participants_cache[key]


def main(systems):
    os.makedirs(OUT_DIR, exist_ok=True)
    built = []
    for system in systems:
        if os.path.exists(f"league_systems/{system}/databases/{system}_database.json"):
            built.append(build_system(system))
    # bereits vorhandene Systeme behalten, wenn nur eines gebaut wurde
    systems_file = os.path.join(OUT_DIR, "data", "systems.json")
    existing = []
    if os.path.exists(systems_file):
        with open(systems_file, encoding="utf8") as fp:
            existing = json.load(fp)
    by_id = {s["id"]: s for s in existing}
    by_id.update({s["id"]: s for s in built})
    ordered = [by_id[s] for s in SYSTEMS if s in by_id]
    with open(systems_file, "w", encoding="utf8") as fp:
        json.dump(ordered, fp, ensure_ascii=False)
    shutil.copy(TEMPLATE, os.path.join(OUT_DIR, "index.html"))
    # Trophaeen-Bilder (Meisterschale/Pokal ohne Gravur) mitkopieren
    tro_src = os.path.join(os.path.dirname(TEMPLATE), "trophaeen")
    if os.path.isdir(tro_src):
        tro_dst = os.path.join(OUT_DIR, "trophaeen")
        os.makedirs(tro_dst, exist_ok=True)
        for fn in os.listdir(tro_src):
            shutil.copy(os.path.join(tro_src, fn), os.path.join(tro_dst, fn))
    open(os.path.join(OUT_DIR, ".nojekyll"), "w").close()
    print(f"🌐 Webseite gebaut: {OUT_DIR}/index.html")


if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    main(args or SYSTEMS)
