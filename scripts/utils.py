from kb4_api.kickbase import Kickbase
import json
import os
from datetime import datetime
import shutil


def zugangsdaten(system):
    """Zugangsdaten des Admin-Accounts eines Ligasystems: (E-Mail, Passwort, Admin-ID).

    Reihenfolge:
      1. Umgebungsvariablen <SYSTEM>_EMAIL, <SYSTEM>_PASSWORT, optional <SYSTEM>_ADMIN_ID
         (z. B. KBL_EMAIL). So kommen sie online aus den GitHub Secrets.
      2. Datei config/<system>.txt (Zeile 1 E-Mail, 2 Passwort, 3 Admin-ID) - lokal wie bisher.
    Fehlt die Admin-ID, wird admin_id aus config/<system>.json genommen.
    """
    prefix = system.upper()
    email = os.environ.get(prefix + "_EMAIL", "").strip()
    passwort = os.environ.get(prefix + "_PASSWORT", "").strip()
    admin_id = os.environ.get(prefix + "_ADMIN_ID", "").strip()

    if not (email and passwort):
        pfad = os.path.join("config", system + ".txt")
        if not os.path.exists(pfad):
            raise SystemExit(
                "❌ Keine Zugangsdaten fuer %s gefunden.\n"
                "   Lokal: Datei %s anlegen (Zeile 1 E-Mail, 2 Passwort, 3 Admin-ID).\n"
                "   Online: GitHub Secrets %s_EMAIL und %s_PASSWORT anlegen."
                % (prefix, pfad, prefix, prefix))
        # utf-8-sig entfernt das unsichtbare BOM-Zeichen, das der Windows-Editor einfuegt
        with open(pfad, encoding="utf-8-sig") as f:
            zeilen = [z.strip() for z in f.read().splitlines() if z.strip()]
        email, passwort = zeilen[0], zeilen[1]
        if not admin_id and len(zeilen) > 2:
            admin_id = zeilen[2]

    if not admin_id:
        try:
            admin_id = str(read_json("config/" + system).get("admin_id") or "")
        except Exception:
            admin_id = ""
    return email, passwort, admin_id


def login_account(system):
    email, passwort, admin_id = zugangsdaten(system)

    kickbase = Kickbase()
    user, leagues = kickbase.login(email, passwort)

    # Nur Ligen, die in config/<system>.json stehen (funktioniert fuer jedes Namensschema)
    namen = set()
    try:
        for lc in read_json("config/" + system).get("leagues", []):
            namen.update(lc.get("names", []))
    except Exception:
        pass
    leagues = [league for league in leagues
               if league.name in namen or (not namen and league.name.startswith(("KBL", "K2BL", "KWBL")))]

    return user, leagues, admin_id, kickbase


# Bevorzugte Reihenfolge auf der Webseite; weitere Systeme werden alphabetisch angehaengt
SYSTEM_REIHENFOLGE = ["kbl", "kwbl", "k2bl", "laliga"]


def alle_systeme():
    """Alle eingerichteten Ligasysteme = alle config/<kuerzel>.json mit league_system_shortcut."""
    gefunden = []
    for fn in os.listdir("config"):
        if not fn.endswith(".json") or "_backup_" in fn:
            continue
        name = fn[:-5]
        try:
            if "league_system_shortcut" in read_json("config/" + name):
                gefunden.append(name)
        except Exception:
            continue
    bekannt = [s for s in SYSTEM_REIHENFOLGE if s in gefunden]
    return bekannt + sorted(s for s in gefunden if s not in bekannt)


def read_json(filename):
    with open(filename + '.json','r', encoding="utf8") as fp:
        data = json.load(fp)
    return data


def write_json(filename, dict, backup=True):
    if not os.path.exists(filename + '.json'):
        with open(filename + '.json', 'w', encoding="utf8") as fp:
            json.dump(dict, fp)
    else:
        if backup == True:
            backup_file(filename)
        with open(filename + '.json', 'w', encoding="utf8") as fp:
            json.dump(dict, fp, indent=4)


def backup_file(filename):
    filename = filename + ".json"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, ext = os.path.splitext(filename)
    backup_filename = f"{base}_backup_{timestamp}{ext}"   
    shutil.copy(filename, backup_filename)
    print(f"💾 Backup of {filename} done.")


def get_current_season(system):
    config = read_json('config/' + system)

    most_recent_season = sorted(
        config['seasons'],
        key=lambda s: s['name'],
        reverse=True
        )[0]
    
    return most_recent_season


def get_kbl_matchday(real_matchday, season, system):
    # For pre season
    if real_matchday == 0:
        return int(0)
    
    config = read_json('config/' + system)
    
    season_data = next((s for s in config["seasons"] if s["name"] == season), None)   
    if season_data is None:
        raise ValueError(f"Season '{season}' not found in config '{system}'.")

    first = int(season_data["first_matchday"])
    last = int(season_data["last_matchday"])

    if not (first <= real_matchday <= last):
        raise ValueError(f"Matchday {real_matchday} not in range {first}-{last} for season {season}.")

    return real_matchday - first + 1


def get_valid_league_names(system):
    # Excludes KBL 6 from database
    config = read_json('config/' + system)
    valid_league_names = set()
    for league_cfg in config["leagues"]:
        if int(league_cfg["level"]) <= int(config["levels_in_database"]):
            valid_league_names.update(league_cfg["names"])
    return valid_league_names


def count_league_wins(system, manager_data, current_season):
    config = read_json("config/" + system)
    
    # Get all league names that are level 1
    level_1_leagues = []
    for league_config in config.get("leagues", []):
        if str(league_config.get("level")) == "1":
            level_1_leagues.extend(league_config.get("names", []))
    
    gold = silver = bronze = 0
    
    for season, data in manager_data.items():
        if not season.startswith("20"):
            continue
        if season >= current_season:
            continue
        if not isinstance(data, dict):
            continue
        
        league = data.get("League")
        place = data.get("Place")

        if league in level_1_leagues and isinstance(place, int):
            if place == 1:
                gold += 1
            elif place == 2:
                silver += 1
            elif place == 3:
                bronze += 1

    # Return emoji summary string
    return "🥇" * gold + "🥈" * silver + "🥉" * bronze


def get_league_movement(system, manager_data, current_season):
    config = read_json("config/" + system)

    # Build a lookup from league name to level
    league_levels = {}
    for league in config.get("leagues", []):
        level = int(league.get("level", -1))
        for name in league.get("names", []):
            league_levels[name] = level

    # Filter seasons before the current one, sorted chronologically
    previous_seasons = [s for s in manager_data if s.startswith("20") and s < current_season]
    if not previous_seasons:
        return "❓"  # No prior seasons

    previous_seasons.sort()
    last_season = previous_seasons[-1]

    current_data = manager_data.get(current_season, {})
    last_data = manager_data.get(last_season, {})

    # Get league names
    current_league = current_data.get("League")
    last_league = last_data.get("League")

    # Convert to levels
    current_level = league_levels.get(current_league)
    last_level = league_levels.get(last_league)

    # Handle missing info
    if current_level is None or last_level is None:
        return "⬆️"

    # Compare levels (lower number = higher league)
    diff = last_level - current_level
    if diff == 0:
        return ""
    elif diff == 1:
        return "⬆️"
    elif diff == 2:
        return "⬆️⬆️"
    elif diff == -1:
        return "⬇️"
    elif diff == -2:
        return "⬇️⬇️"
    elif diff > 2:
        return "⬆️" * diff
    elif diff < -2:
        return "⬇️" * abs(diff)

    return "⬆️"


def count_kbl_cup_wins(system, player_id, current_season):
    cup_dir = f"league_systems/{system}/cup"
    cup_wins = 0
    prefix = f"{system.upper()}Cup_Database_"   # vorher fest "KBLCup_" -> KWBL-Pokalsiege wurden nie gezaehlt

    # List all cup files
    for filename in os.listdir(cup_dir):
        if filename.startswith(prefix) and filename.endswith(".json") and "_backup_" not in filename:
            season = filename.replace(prefix, "").replace(".json", "")

            # Only consider seasons before the current season
            if season >= current_season:
                continue

            file_path = os.path.join(cup_dir, filename)
            with open(file_path, "r", encoding="utf-8") as file:
                cup_data = json.load(file)

            final = cup_data.get("2", {})
            winners = final.get("Winners", [])

            if str(player_id) in [str(w) for w in winners]:
                cup_wins += 1

    # Return trophy emojis based on win count
    return "🏆" * cup_wins

# ---------------------------------------------------------------------------
# Admin-Korrekturen
# ---------------------------------------------------------------------------
# Kickbase-Admins koennen seit Sommer 2026 Punkte gutschreiben. Diese Punkte
# tauchen NICHT in den Spieltagspunkten (mdp) auf, sondern nur in den
# Gesamtpunkten (tp). Wir speichern sie pro Saison unter
#     database[manager][season]["Corrections"] = {"<kbl-spieltag>": punkte, ...}
# Der Schluessel ist der Spieltag, an dem die Korrektur erfasst wurde.

def get_corrections(season_data):
    """Dict {spieltag(int): punkte} der Admin-Korrekturen einer Saison."""
    corr = (season_data or {}).get("Corrections") or {}
    return {int(k): v for k, v in corr.items()}


def correction_upto(season_data, matchday_kbl):
    """Summe aller Korrekturen bis einschliesslich KBL-Spieltag matchday_kbl."""
    return sum(v for k, v in get_corrections(season_data).items() if k <= matchday_kbl)


def total_points_upto(season_data, matchday_kbl):
    """Gesamtpunkte bis Spieltag X = Spieltagspunkte + Admin-Korrekturen."""
    md_points = (season_data or {}).get("MdPoints") or []
    md_sum = sum(p or 0 for p in md_points[1:matchday_kbl + 1])
    return md_sum + correction_upto(season_data, matchday_kbl)


def record_correction(season_data, matchday_kbl, correction_total):
    """Speichert neue Korrekturen. correction_total ist die laut Kickbase
    aktuell gueltige Gesamtkorrektur (tp - Summe aller mdp). Neu ist nur der
    Teil, der noch nicht gespeichert ist; der wird dem Spieltag zugeordnet.
    Gibt den neu erfassten Betrag zurueck (0 = nichts Neues)."""
    corr = season_data.setdefault("Corrections", {})
    known = sum(corr.values())
    delta = round(correction_total - known)
    if delta != 0:
        key = str(matchday_kbl)
        corr[key] = corr.get(key, 0) + delta
        if corr[key] == 0:
            del corr[key]
    return delta
