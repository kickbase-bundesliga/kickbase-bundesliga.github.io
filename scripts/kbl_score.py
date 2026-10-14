import json
import csv
import os.path
from os import path
import plotly as py
import plotly.graph_objects as go
import numpy as np
import time
import sys
sys.path.append("./")
from scripts import utils, table_image_creator


def main(system):
    tablelist, seasons = update_kbl_score(system)

    tablelist.sort(key=lambda x:x[-1],reverse=True)
    for i in range(len(tablelist)):
        tablelist[i].insert(0,i+1)

    filename = f"league_systems/{system}/tables/{seasons[-1]}_KBLScore"
    table_image_creator.save_kblscore_table_as_image(system, tablelist, seasons, filename)


def update_kbl_score(system):
    config = utils.read_json('config/' + system)   
    filename = "league_systems/" + system + "/databases/" + system + "_database"
    database = utils.read_json(filename)
    seasons = []
    tablelist = []
    for season in reversed(config['seasons']):
        seasons.append(season['name'])

    # Loop over all managers in database
    for manager_id in database:
        if str(manager_id) != str(config['admin_id']):
            score_ges = 0
            score_cup = 0
            score_array = []

            # Loop over all seasons in config file
            for season in seasons:
                try:
                    place = database[manager_id][season]["Place"]
                except:
                    place = None
                if place is None:
                    score = 0
                    league = " - "
                else:

                    # Get KBL cup round of manager
                    league = database[manager_id][season]["League"]
                    try:
                        database_cup = opendatabase_cup(system, season)
                        cup_round = get_cup_round(database_cup, manager_id)
                    except:
                        cup_round = 32

                    # Get KBL score of manager
                    score = calculate_score(place, league, config)
                    score_cup = calculate_score_cup(cup_round, config)
                score_ges = score_ges + score + score_cup

                # For the table: First seasons did not have a KBL Cup
                if season in ["2020A","2020B","2021A","2021B","2022A"]:
                    score_array.append(str(score))
                else:
                    score_array.append(str(score) + " (" + str(score_cup) + ")")
                score_cup = 0

            # Write into database and get more information for table
            database[manager_id]["Info"]["KBL Score"] = score_ges
            username = database[manager_id]["Username"]
            try:
                current_league = database[manager_id]["Info"]["League"][6:]
            except:
                current_league = ' - '
            column = [username, current_league] + score_array + [score_ges]
            if score_ges != 0:
                tablelist.append(column)

    utils.write_json(filename, database, True)
    return tablelist, seasons


def calculate_score(place, league, config):
    if place == 18:
        place = 17 
    for league_config in config.get("leagues", []):
        if league in league_config.get("names", []):
            scores = league_config.get("kbl_score", [])
            if 1 <= place <= len(scores):
                return scores[place - 1]
            else:
                return 0  # Invalid place
    return 0  # League not found


def calculate_score_cup(cup_round, config):
    cup_scores = config.get("cup_scores", [])
    cup_rounds = [0, 2, 4, 8, 16, 32]
    if cup_round in cup_rounds:
        index = cup_rounds.index(cup_round)
        if index < len(cup_scores):
            return cup_scores[index]
    return 0  # Default score if cup_round not matched or index out of range


def get_cup_round(database_cup, manager_id):
    if manager_id in database_cup["2"]["Winners"]:
        cround = 0
        return cround
    if manager_id in database_cup["4"]["Winners"]:
        cround = 2
        return cround
    if manager_id in database_cup["8"]["Winners"]:
        cround = 4
        return cround
    if manager_id in database_cup["16"]["Winners"]:
        cround = 8
        return cround
    if manager_id in database_cup["32"]["Winners"]:
        cround = 16
        return cround
    cround = 32
    return cround


def opendatabase_cup(system, season):
    # Opens cup database of given season.
    path = "league_systems/" + system + "/cup/"
    jsonname = path + system.upper() + 'Cup_Database_' + season + '.json'  # Gross-/Kleinschreibung wie beim Anlegen
    print(jsonname)
    with open(jsonname,'r', encoding="utf8") as fp:
        database = json.load(fp)
    return database