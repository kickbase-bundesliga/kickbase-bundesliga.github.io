"""
This script needs to be callled if the data of a new matchday should be added to the local database.
"""

import sys
sys.path.append("./")
from scripts import utils


def fill_database(system, matchday_real, season):
    matchday_kbl = utils.get_kbl_matchday(matchday_real, season["name"], system)
    user, leagues, adm_id, kickbase = utils.login_account(system)
    filename = f"league_systems/{system}/databases/{system}_database"
    utils.backup_file(filename)
    valid_league_names = utils.get_valid_league_names(system)
    database = utils.read_json(filename)

    # Loop over all leagues and managers
    for league in leagues:
        if league.name in valid_league_names:
            managers = kickbase.league_users(league)
            for manager in managers:
                manager_id = manager.i

                # If it's not the admin, extract data from API
                if manager_id != adm_id:
                    print(f"➕ Adding data for {manager.n} with the ID {manager_id}.")
                    managerProfile = kickbase.league_user_dashboard(league, manager_id)
                    managerSeasonStats = kickbase.league_user_performance(league, manager_id)

                    correction_total = None
                    try:
                        season_info = managerSeasonStats.it[-1]
                        if matchday_kbl != 0 and season_info['it'] == []:
                            season_info = managerSeasonStats.it[-2]
                        manager_total_points = season_info['tp']
                        mday_info = season_info['it'][matchday_kbl - 1]
                        manager_mdPoints = mday_info['mdp']
                        manager_mdPlace = managerProfile.pl
                        # Admin-Korrektur = Gesamtpunkte laut Kickbase minus Summe ALLER
                        # Spieltagspunkte aus derselben Antwort (nicht aus unserer DB,
                        # sonst wuerden beim Nachtragen alter Spieltage die Punkte
                        # spaeterer Spieltage faelschlich als Korrektur gelten).
                        correction_total = manager_total_points - sum(
                            (md.get('mdp') or 0) for md in season_info['it'])
                        print(f"   His matchday points are: {manager_mdPoints}.")
                    # It the extracting is not possible, assume 0 points.
                    except Exception:
                        manager_total_points = 0
                        manager_mdPoints = 0
                        manager_mdPlace = 17
                        print("   Exception, no data found, adding 0 points and last place")

                    update_database_in_memory(
                        database, matchday_kbl, season["name"], league.name,
                        manager_id, manager.n, managerProfile.pl,
                        manager_total_points, manager_mdPoints, manager_mdPlace
                    )

                    if correction_total is not None:
                        delta = utils.record_correction(
                            database[manager_id][season["name"]], matchday_kbl, correction_total)
                        if delta:
                            print(f"   ✏️  Admin-Korrektur erkannt: {delta:+d} Punkte (Spieltag {matchday_kbl}).")

    rank_managers_by_total_mdpoints(database, leagues, valid_league_names, season["name"], matchday_kbl, kickbase)
    utils.write_json(filename, database, True)


def rank_managers_by_total_mdpoints(database, leagues, valid_league_names, season_name, matchday_kbl, kickbase):
    for league in leagues:
        if league.name not in valid_league_names:
            continue

        league_managers = []
        for manager in kickbase.league_users(league):
            manager_id = manager.i
            if manager_id in database and season_name in database[manager_id]:
                # Platzierung inkl. Admin-Korrekturen
                total = utils.total_points_upto(database[manager_id][season_name], matchday_kbl)
                league_managers.append((manager_id, total))

        # Sort managers descending by total points
        ranked = sorted(league_managers, key=lambda x: x[1], reverse=True)

        for rank, (manager_id, _) in enumerate(ranked, start=1):
            if season_name in database[manager_id]:
                sdata = database[manager_id][season_name]
                sdata.setdefault('MdPlace', [])
                sdata['MdPlace'][matchday_kbl] = rank
                # Die Platzierung aus dem Kickbase-Dashboard (pl) beruecksichtigt
                # Admin-Korrekturen nicht. Deshalb den Platz selbst setzen - aber nur,
                # wenn dies der neueste eingetragene Spieltag ist (Nachtragen alter
                # Spieltage soll den aktuellen Platz nicht ueberschreiben).
                filled = [i for i, p in enumerate(sdata.get('MdPoints', [])) if p]
                if not filled or matchday_kbl >= filled[-1]:
                    sdata['Place'] = rank
                    database[manager_id]['Info']['Place'] = rank


def pre_season(system, season):
    matchday_kbl = 0
    user, leagues, adm_id, kickbase = utils.login_account(system)
    filename = f"league_systems/{system}/databases/{system}_database"
    valid_league_names = utils.get_valid_league_names(system)
    database = utils.read_json(filename)

    for league in leagues:
        if league.name in valid_league_names:
            managers = kickbase.league_users(league)
            for manager in managers:
                manager_id = manager.i

                if manager_id != adm_id:
                    print(f"➕ Adding preseason data for {manager.n} with ID {manager_id}.")                   
                    manager_place = 0
                    manager_points = 0
                    manager_mdPoints = 0
                    manager_mdPlace = 0

                    update_database_in_memory(
                        database, matchday_kbl, season["name"], league.name,
                        manager_id, manager.n, manager_place,
                        manager_points, manager_mdPoints, manager_mdPlace
                    )

    utils.write_json(filename, database, True)
                    

def update_database_in_memory(database, matchday_kbl, season, l_name, m_id, m_name, m_place, m_points, m_mdPoints, m_mdPlace):
    database[m_id]['Username'] = m_name
    database[m_id]['Info']['League'] = l_name
    database[m_id]['Info']['Place'] = m_place
    database[m_id][season]['League'] = l_name
    database[m_id][season]['Place'] = m_place
    database[m_id][season]['Points'] = m_points
    database[m_id][season]['MdPoints'][matchday_kbl] = m_mdPoints
    database[m_id][season]['MdPlace'][matchday_kbl] = m_mdPlace


def main():
    valid_systems = {"kbl", "k2bl", "kwbl"}
    while True:
        system = input("❓ Which league system data do you want to update? (kbl/k2bl/kwbl): ").strip().lower()       
        if system in valid_systems:
            print(f"✅ Selected {system.upper()}.")
            break
        else:
            print("❌ Invalid selection. Please enter 'kbl', 'k2bl', or 'kwbl'.")

    season = utils.get_current_season(system)
    print("    Current season: " + season["name"])

    first_md = int(season['first_matchday'])
    last_md = int(season['last_matchday'])

    while True:
        response = input(f"❓ Please enter a matchday number between {first_md} and {last_md} for which you want to update the database (0 for pre-season): ").strip().lower()
        try:
            matchday = int(response)
            if first_md <= matchday <= last_md:
                break
            elif matchday == 0:
                break
            else:
                print(f"❌ Matchday must be between {first_md} and {last_md}.")
        except ValueError:
            print("❌ Invalid input. Please enter a whole number.")

    if matchday == 0:
        pre_season(system, season)
    else:
        fill_database(system, matchday, season)


if __name__ == "__main__":
    main()