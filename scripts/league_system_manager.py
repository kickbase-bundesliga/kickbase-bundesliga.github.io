"""
This script is for creating a new database for a whole league system based on the corresponding config json.
Also it's used for adding new managers and the new season at the beginning of a season.
This should be done when all managers are in their corresponding leagues, but the season hasn't yet startet.
"""
import sys
sys.path.append("./")
import os
from scripts import utils


def create_system(system):
    # Create directories
    os.makedirs("league_systems/" + system, exist_ok=True)
    os.makedirs("league_systems/" + system + "/databases", exist_ok=True)
    os.makedirs("league_systems/" + system + "/tables", exist_ok=True)
    os.makedirs("league_systems/" + system + "/cup", exist_ok=True)

    # Get all manager ids and create dictionary entry
    user, leagues, adm_id, kickbase = utils.login_account(system)
    config = utils.read_json('config/' + system)
    valid_league_names = utils.get_valid_league_names(system) 
    database =  {}

    for league in leagues:
        if league.name in valid_league_names:
            managers = kickbase.league_users(league)
            for manager in managers:
                # Ignore admin account
                if manager.i != adm_id:
                    database[int(manager.i)] = {
                        "Username": None,
                        "Info": {
                            "KBL Score": None,
                            "League": None,
                            "Place": None
                            }
                        }
                    for season in reversed(config['seasons']):
                        database[int(manager.i)][season['name']] = {
                            "League": None, 
                            "Place": None, 
                            "Points": None,
                            "MdPoints": [0] * (int(season['matchday_number']) + 1),
                            "MdPlace": [0] * (int(season['matchday_number']) + 1),
                            }
                    
    # Write database
    filename = "league_systems/" + system + "/databases/" + system + "_database"
    utils.write_json(filename, database)
    print("✅ System " + system + " created!")
    

def add_new_season(system):
    # Get database, config and leagues
    filename = "league_systems/" + system + "/databases/" + system + "_database"
    database = utils.read_json(filename)
    user, leagues, adm_id, kickbase = utils.login_account(system)
    config = utils.read_json('config/' + system)

    # Extract list of all player IDs currently in the system
    id_list = []
    valid_league_names = utils.get_valid_league_names(system)
    for league in leagues:
        if league.name in valid_league_names:
            managers = kickbase.league_users(league)
            for manager in managers:
                id_list.append(int(manager.i))
    adm_id = int(adm_id)  # ensure type match
    id_list = [id for id in id_list if id != adm_id]

    # Perform changes on database and write it to file
    change_database(id_list, database, config)
    remove_players_who_left(id_list, database)
    utils.write_json(filename, database)


def change_database(id_list, database, config):
    # Loop over all player IDs
    for manager_id in id_list:
        # If it already exists, add seasons not yet included from the config system json
        if str(manager_id) in database:
            for season in reversed(config['seasons']):
                if season['name'] not in database[str(manager_id)]:
                    database[str(manager_id)][season['name']] = {
                        "League": None, 
                        "Place": None, 
                        "Points": None,
                        "MdPoints": [0] * (int(season['matchday_number']) + 1),
                        "MdPlace": [0] * (int(season['matchday_number']) + 1),
                    }
                    print("➕ Added season " + season['name'] + " to the database of manager ID " + str(manager_id))
        # Else, add everything
        else:
            database[int(manager_id)] = {
                    "Username": None,
                    "Info": {
                        "KBL Score": None,
                        "League": None,
                        "Place": None
                        }
                    }
            for season in reversed(config['seasons']):
                database[int(manager_id)][season['name']] = {
                    "League": None, 
                    "Place": None, 
                    "Points": None,
                    "MdPoints": [0] * (int(season['matchday_number']) + 1),
                    "MdPlace": [0] * (int(season['matchday_number']) + 1),
                    }
            print("➕ Created database entry for manager ID " + str(manager_id))
    return database


def remove_players_who_left(id_list, database):
    # Remove the League entry of players who left the system
    for key in database:
        if int(key) not in id_list:
            print("➖ Manager ID " + key + " left the league system, so his league is set to None.")
            if database[key]["Info"]["League"] is not None:               
                database[key]["Info"]["League"] = None
    return database


def main():
    valid_systems = {"kbl", "k2bl", "kwbl"}
    valid_responses = {"create system", "new season"}

    # Prompt for league system
    while True:
        system = input("❓ Which league system do you want to manage? (kbl/k2bl/kwbl): ").strip().lower()
        if system in valid_systems:
            print(f"✅ Managing {system.upper()}.")
            break
        else:
            print("❌ Invalid selection. Please enter 'kbl', 'k2bl', or 'kwbl'.")

    # Prompt for action
    while True:
        response = input("❓ What do you want to do? (create system/new season): ").strip().lower()
        if response in valid_responses:
            if response == "create system":
                print(f"✅ Creating new league system based on {system}.json!")
                create_system(system)
            elif response == "new season":
                print(f"✅ Adding new season to existing {system} database based on {system}.json")
                add_new_season(system)
            break
        else:
            print("❌ Invalid selection. Please enter 'create system' or 'new season'.")


if __name__ == "__main__":
    main()