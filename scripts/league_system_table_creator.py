"""
This script needs to be called when wanting to create new tables.
"""

import sys
sys.path.append("./")
from scripts import utils, kbl_score, table_image_creator

def generate_matchday_tables(system, season, matchday_kbl, league):
    filename = "league_systems/" + system + "/databases/" + system + "_database"
    database = utils.read_json(filename)
    table = []

    for player_id, player_data in database.items():
        season_data = player_data.get(season)
        if not season_data:
            continue

        # Check, if the manager plays in the stated league
        if season_data.get("League") != league:
            continue

        username = player_data.get("Username")
        md_points = season_data.get("MdPoints", [])
        md_place = season_data.get("MdPlace", [])
        # Gesamtpunkte inkl. Admin-Korrekturen (vorher nur Summe der Spieltagspunkte)
        correction = utils.correction_upto(season_data, matchday_kbl)
        total_points = utils.total_points_upto(season_data, matchday_kbl)
        current_md_points = md_points[matchday_kbl] if len(md_points) >= matchday_kbl else None
        current_md_place = md_place[matchday_kbl] if len(md_place) >= matchday_kbl else None

        # Calculate trend (previous place - current place)
        if matchday_kbl > 0:
            previous_md_place = md_place[matchday_kbl - 1]
            if previous_md_place is not None and current_md_place is not None:
                trend_val = previous_md_place - current_md_place
                if trend_val > 0:
                    trend = f"↗ +{trend_val}"
                elif trend_val < 0:
                    trend = f"↘ {trend_val}"
                else:
                    trend = "→ 0"
            else:
                trend = "?"
        else:
            trend = "?"  # no previous matchday

        # Add emojis to username for titles, promotions/relegations
        username =  username + " " + utils.get_league_movement(system, player_data, season)
        username = username + " " + utils.count_league_wins(system, player_data, season)
        username = username + " " + utils.count_kbl_cup_wins(system, player_id, season)

        table.append({
            "Place": current_md_place,
            "Trend": trend,
            "Manager": username,
            "MD": current_md_points,
            "Korr.": correction,
            "Points": total_points
        })

    table.sort(key=lambda x: x["Points"] if x["Points"] is not None else -1, reverse=True)
    for i, row in enumerate(table):
        row['Place'] = i + 1

    # Korrektur-Spalte nur anzeigen, wenn es in dieser Liga eine gibt
    if any(row["Korr."] for row in table):
        for row in table:
            row["Korr."] = f"{row['Korr.']:+d}" if row["Korr."] else ""
    else:
        for row in table:
            del row["Korr."]

    filename_image = f"league_systems/{system}/tables/{season}_Matchday{matchday_kbl}_{league}"
    logo_path = f"league_systems/{system}/logo.png"
    table_image_creator.save_matchday_table_as_image(table, season, matchday_kbl, league, "config/" + system, filename_image, logo_path)


def generate_kbl_score_table(system):
    kbl_score.main(system)  

def generate_all_time_table(system, league):
    config = utils.read_json('config/' + system)   
    filename = "league_systems/" + system + "/databases/" + system + "_database"
    database = utils.read_json(filename)
    seasons = []
    tablelist = [[0, 0, 0, 0, 0, 0]]
    current_season = utils.get_current_season(system)

    for s in reversed(config['seasons']):
        seasons.append(s['name'])   
    
    # Loop over all seasons, keys and check if the manager played in this league this season.
    for j in range(0,len(seasons)):
        for key in list(database.keys()):
            if seasons[j] in database[key]:
                if database[key][seasons[j]]['League'] is not None:
                    if league in database[key][seasons[j]]['League']:

                        # Get current league
                        try:
                            currentleague = 'KBL ' + database[key]['Info']['League'][11:]
                        except:
                            currentleague = ' - '

                        # Get kbl score
                        try:
                            kbl_score = database[key]['Info']['KBL Score']
                        except:
                            kbl_score = 0

                        pointsGES = database[key][seasons[j]]['Points']

                        # Get matchday number of season
                        matchday_number = next(
                            (int(season["matchday_number"]) for season in config["seasons"] if season["name"] == seasons[j]), 17)
                        column = [key, currentleague, kbl_score, matchday_number, pointsGES, pointsGES]

                        # If key in table, append. Else, update.
                        keys_in_table = [row[0] for row in tablelist]
                        if key not in keys_in_table:
                            tablelist.append(column)
                        else:
                            for i, row in enumerate(tablelist):
                                if row[0] == key:
                                    tablelist[i][1] = currentleague
                                    tablelist[i][4] += pointsGES
                                    tablelist[i][5] += pointsGES
                                    tablelist[i][3] += matchday_number

    tablelist.pop(0)
    tablelist.sort(key=lambda x:x[5],reverse=True)

    # Add ranking number
    for i in range(len(tablelist)):
        tablelist[i].insert(0,i+1)

    # Replace key with manager name and calculate average points
    for i in range(len(tablelist)):
        key = tablelist[i][1]
        tablelist[i][1] = database[key]['Username']
        tablelist[i][5] = round((tablelist[i][6])/(tablelist[i][4]))

    header = [
        'Saison:<br>' + str(current_season['name']), 
        league + ': Ewige Tabelle',
        'Letzte Liga',
        'KBL Score',
        'Spieltage',
        '<b>Ø Punkte <br>(Spieltag)<b>',
        '<b>Punkte <br>(Gesamt)<b>'
              ]
    columnwid = [11, 37, 15, 15, 15, 15, 13]
    filename_image = f"league_systems/{system}/tables/{str(current_season['name'])}_{league}_EwigeTabelle"
    table_image_creator.save_alltime_table_as_image(filename_image, tablelist, header, columnwid)


def main():
    valid_systems = {"kbl", "k2bl", "kwbl"}
    valid_table_types = {"matchday", "all time", "kbl score"}

    # Step 1: Choose league system
    while True:
        system = input("❓ Which league system do you want tables for? (kbl/k2bl/kwbl): ").strip().lower()
        if system in valid_systems:
            print(f"✅ Selected system: {system.upper()}")
            break
        else:
            print("❌ Invalid input. Please enter 'kbl', 'k2bl', or 'kwbl'.")

    # Step 2: Choose table type
    while True:
        table_type = input("❓ Which table type do you want? (matchday/all time/kbl score): ").strip().lower()
        if table_type in valid_table_types:
            print(f"✅ Selected table type: {table_type}")
            break
        else:
            print("❌ Invalid input. Please enter 'matchday', 'all time', or 'kbl score'.")

    # Step 3a: If matchday table, get more details
    if table_type == "matchday":
        # Season
        while True:
            season = input("❓ Which season? (e.g., 2025A or 2024BA (KWBL)): ").strip()
            if season:  # Simple validation; optionally validate format
                print("⚠️  Warning: This command may not work for some matchdays before 2025B.")
                break
            print("❌ Please enter a valid season name (e.g., 2025A).")
        
        # Matchday
        while True:
            matchday = input("❓ Which matchday? (enter number of real matchday): ").strip()
            if matchday.isdigit() and int(matchday) >= 0:
                matchday = int(matchday)
                matchday_kbl = utils.get_kbl_matchday(matchday, season, system)
                break
            print("❌ Please enter a valid positive matchday number.")
        
        # All leagues or specific one
        while True:
            scope = input("❓ Do you want the table for all leagues or a specific one? (all/specific): ").strip().lower()

            if scope == "all":
                print("✅ Generating matchday tables for all leagues...")
                config = utils.read_json('config/' + system)
                valid_league_names = utils.get_valid_league_names(system)
                for league in config["leagues"]:
                    for league_name in league["names"]:
                        if league_name in valid_league_names:
                            generate_matchday_tables(system, season, matchday_kbl, league_name)
                break

            elif scope == "specific":
                league_name = "KBL - Liga " + input("Enter the name of the league (e.g., 1 or 4A): ").strip()
                print(f"✅ Generating matchday table for league: {league_name}...")
                generate_matchday_tables(system, season, matchday_kbl, league_name)
                break

            else:
                print("❌ Invalid input. Please enter 'all' or 'specific'.")

    # Step 3b: If all time table, get more details
    elif table_type == "all time":
        # All leagues or specific one
        while True:
            scope = input("❓ Do you want the table for all leagues or a specific one? (all/specific): ").strip().lower()

            if scope == "all":
                print("✅ Generating all time tables for all leagues...")
                config = utils.read_json('config/' + system)
                valid_league_names = utils.get_valid_league_names(system)
                for league in config["leagues"]:
                    for league_name in league["names"]:
                        if league_name in valid_league_names:
                            generate_all_time_table(system, league_name)
                break

            elif scope == "specific":
                league_name = "KBL - Liga " + input("Enter the name of the league (e.g., 1 or 4A): ").strip()
                print(f"✅ Generating all time table for league: {league_name}...")
                generate_all_time_table(system, league_name)
                break

            else:
                print("❌ Invalid input. Please enter 'all' or 'specific'.")

    # Step 3c: Call kbl score
    elif table_type == "kbl score":
        generate_kbl_score_table(system)    

if __name__ == "__main__":
    main()