import csv
import os
import json
import random
import copy
import sys

sys.path.append("./")
from scripts import utils
from scripts import table_image_creator

def create_new_cup(system, season):
    folder = f"league_systems/{system}/cup/"
    jsonname = f"{folder}{system.upper()}Cup_Database_{season}"

    if os.path.exists(jsonname + ".json"):
        print("⚠️ A cup already exists for this season. Aborting creation.")
        return

    filename = f"{folder}{system.upper()}Cup_Participants_{season}.csv"
    with open(filename, newline='', encoding="utf8") as csvfile:
        reader = csv.reader(csvfile, delimiter=',', quotechar='|')
        data = list(reader)

    participants = [row[1:4] for row in data[1:]]
    all_participants = copy.deepcopy(participants)

    p = len(participants)
    teams = 2 ** (p - 1).bit_length()
    n_bye = teams - p
    database = {teams: {"Matchups": [], "Results": [], "Winners": []}}

    matchups = []
    tablelist = []

    bye_count = assign_byes_by_score(system, participants, matchups, tablelist, n_bye)

    while bye_count < n_bye:
        participant = participants.pop(0)
        matchups.append([participant[0], "Freilos"])
        tablelist.append([participant[2], participant[1][:22], findKBLScore(system, participant[0]), '-', '', 'Freilos', ''])
        bye_count += 1

    while participants:
        m1 = participants.pop(random.randrange(len(participants)))
        m2 = participants.pop(random.randrange(len(participants)))
        matchups.append([m1[0], m2[0]])
        tablelist.append([m1[2], m1[1][:22], findKBLScore(system, m1[0]), '-', findKBLScore(system, m2[0]), m2[1][:22], m2[2]])

    database[teams]["Matchups"] = matchups
    utils.write_json(jsonname, database, True)

    header = ['Liga', 'Manager', f'{system.upper()} Score', '', f'{system.upper()} Score', 'Manager', 'Liga']
    tablename = f'{season}_KBLCup_Round{teams}_Matchups'
    foldername = f"league_systems/{system}/tables/"
    table_image_creator.save_cup_round_as_image(tablelist, header, tablename, foldername, is_results=False)
    print("✅ Cup created successfully!")


def assign_byes_by_score(system, participants, matchups, tablelist, n_bye):
    scored_participants = [(parti, findKBLScore(system, parti[0])) for parti in participants]
    scored_participants.sort(key=lambda x: x[1], reverse=True)
    bye_count = 0
    for parti, score in scored_participants[:n_bye]:
        matchups.append([parti[0], "Freilos"])
        tablelist.append([parti[2], parti[1][:22], score, '-', '', 'Freilos', ''])
        participants.remove(parti)
        bye_count += 1
    return bye_count


def get_latest_round(database):
    try:
        return str(min(map(int, database.keys())))
    except ValueError:
        return None


def get_round_results(system, season, matchday):
    folder = f"league_systems/{system}/cup/"
    json_path = f"{folder}{system.upper()}Cup_Database_{season}"
    database = utils.read_json(json_path)

    current_round = get_latest_round(database)
    if not current_round or not database[current_round]["Matchups"]:
        print("⚠️ No matchups found. Please draw the round first.")
        return

    matchups = database[current_round]['Matchups']
    results = []

    print(f"📊 Evaluating round {current_round} results...")

    for m1, m2 in matchups:
        points_m1 = 0 if m1 == "Freilos" else find_points(system, m1, season, utils.get_kbl_matchday(matchday, season, system))
        points_m2 = 0 if m2 == "Freilos" else find_points(system, m2, season, utils.get_kbl_matchday(matchday, season, system))
        results.append([[m1, points_m1], [m2, points_m2]])

    database[current_round]['Results'] = results

    winners = []
    for res in results:
        m1, p1 = res[0]
        m2, p2 = res[1]
        if p1 > p2 or m2 == "Freilos":
            winners.append(m1)
        elif p2 > p1:
            winners.append(m2)
        elif p1 == p2:
            winners.append(str(min(int(m1), int(m2))))
        else:
            print("❌ Unexpected result error.")

    database[current_round]['Winners'] = winners
    utils.write_json(json_path, database, True)

    database_all = utils.read_json(f"league_systems/{system}/databases/{system}_database")
    tablelist = []

    for res in results:
        id1, pts1 = res[0]
        id2, pts2 = res[1]
        name1, league1 = ("Freilos", "") if id1 == "Freilos" else get_manager_info(database_all, id1, season)
        name2, league2 = ("Freilos", "") if id2 == "Freilos" else get_manager_info(database_all, id2, season)

        factor1 = get_cup_factor(system, league1)
        factor2 = get_cup_factor(system, league2)

        row = [f"KBL {league1[11:]} ({factor1})", name1[:18], pts1, "-", pts2, name2[:18], f"KBL {league2[11:]} ({factor2})"]
        tablelist.append(row)

    header = ['Liga', 'Manager', 'Punkte', '', 'Punkte', 'Manager', 'Liga']
    tablename = f"{season}_KBLCup_Round{current_round}_Results"
    table_image_creator.save_cup_round_as_image(tablelist, header, tablename, f"league_systems/{system}/tables/", is_results=True)
    print("✅ Results generated and saved.")


def get_cup_factor(system, league):
    config = utils.read_json(f"config/{system}")
    for league_conf in config.get("leagues", []):
        if league in league_conf.get("names", []):
            return league_conf.get("cup_factor", 0)
    return 0


def get_manager_info(database_all, manager_id, season):
    try:
        name = database_all[manager_id]['Username']
        league = database_all[manager_id][season]['League']
        return name, league
    except:
        return "Falsche ID Kollege", ""


def find_points(system, manager_id, season, matchday):
    config = utils.read_json(f"config/{system}")
    filename = f"league_systems/{system}/databases/{system}_database"
    database_all = utils.read_json(filename)

    manager_data = database_all.get(manager_id)
    if not manager_data:
        print(f"❌ Manager not found: {manager_id}")
        return 0

    season_data = manager_data.get(season, {})
    md_points = season_data.get("MdPoints", [])
    points_md = md_points[matchday] if isinstance(md_points, list) and matchday < len(md_points) else 0

    league = season_data.get("League") or manager_data.get("Info", {}).get("League", "")
    cup_factor = get_cup_factor(system, league)
    return round(points_md * cup_factor)


def draw_new_round(system, season):
    folder = f"league_systems/{system}/cup/"
    json_path = f"{folder}{system.upper()}Cup_Database_{season}"
    database = utils.read_json(json_path)

    current_round = get_latest_round(database)
    winners = database[str(current_round)]["Winners"].copy()

    if not winners:
        print("❌ No winners found in current round. Please generate results first.")
        return

    next_round = int(current_round) // 2
    matchups = []
    tablelist = []

    random.shuffle(winners)

    while len(winners) >= 2:
        m1 = winners.pop()
        m2 = winners.pop()
        matchups.append([m1, m2])
        name1, league1 = get_manager_info(utils.read_json(f"league_systems/{system}/databases/{system}_database"), m1, season)
        name2, league2 = get_manager_info(utils.read_json(f"league_systems/{system}/databases/{system}_database"), m2, season)
        tablelist.append([f'{system.upper()} ' + league1[11:], name1[:22], findKBLScore(system, m1), '-', findKBLScore(system, m2), name2[:22], f'{system.upper()} ' + league2[11:]])

    if winners:
        m1 = winners.pop()
        matchups.append([m1, "Freilos"])
        name1, league1 = get_manager_info(utils.read_json(f"league_systems/{system}/databases/{system}_database"), m1, season)
        tablelist.append([f'{system.upper()} ' + league1[11:], name1[:22], findKBLScore(system, m1), '-', '', 'Freilos', ''])

    database[str(next_round)] = {"Matchups": matchups, "Results": [], "Winners": []}
    utils.write_json(json_path, database, True)

    header = ['Liga', 'Manager', f'{system.upper()} Score', '', f'{system.upper()} Score', 'Manager', 'Liga']
    tablename = f"{season}_KBLCup_Round{next_round}_Matchups"
    foldername = f"league_systems/{system}/tables/"
    table_image_creator.save_cup_round_as_image(tablelist, header, tablename, foldername, is_results=False)
    print(f"✅ New round ({next_round}) drawn and saved successfully.")


def findKBLScore(system, manager_id):
    filename = f"league_systems/{system}/databases/{system}_database"
    database_all = utils.read_json(filename)
    manager_data = database_all.get(manager_id)
    if manager_data:
        return manager_data.get('Info', {}).get('KBL Score') or 0
    return -69


def main():
    valid_systems = {"kbl", "k2bl", "kwbl"}
    while True:
        system = input("Which cup system do you want to manage? (kbl/k2bl/kwbl): ").strip().lower()
        if system in valid_systems:
            print(f"✅ Selected {system.upper()} cup system.")
            break
        else:
            print("❌ Invalid selection. Please enter 'kbl', 'k2bl', or 'kwbl'.")

    season = utils.get_current_season(system)
    print(f"📅 Current season: {season['name']}")

    valid_actions = {"create", "results", "draw"}
    while True:
        action = input("Do you want to create a new cup, get round results or draw a new round? (create/results/draw): ").strip().lower()
        if action in valid_actions:
            print(f"✅ Action selected: {action}")
            break
        else:
            print("❌ Invalid action. Please enter 'create', 'results', or 'draw'.")

    if action == "create":
        create_new_cup(system, season["name"])
    elif action == "results":
        first_md = int(season['first_matchday'])
        last_md = int(season['last_matchday'])
        while True:
            response = input(f"For which real matchday do you want round results? Enter a number between {first_md} and {last_md}: ").strip().lower()
            try:
                matchday = int(response)
                if first_md <= matchday <= last_md:
                    get_round_results(system, season["name"], matchday)
                    break
                else:
                    print(f"❌ Matchday must be between {first_md} and {last_md}.")
            except ValueError:
                print("❌ Invalid input. Please enter a whole number.")
    elif action == "draw":
        draw_new_round(system, season["name"])

if __name__ == "__main__":
    main()
