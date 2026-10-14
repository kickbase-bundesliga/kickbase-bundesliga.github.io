"""
Alles in einem Rutsch nach einem Spieltag:

    python update.py kbl 5            Daten fuer Bundesliga-Spieltag 5 holen, Tabellenbilder,
                                      KBL-Score und Webseite neu erzeugen
    python update.py kbl 5 --pokal    zusaetzlich die Pokalrunde mit Spieltag 5 auswerten
    python update.py kwbl 6 --ohne-bilder
    python update.py kbl 5 --ohne-extras  ohne Kaderwerte/Aufstellungen/Elfen des Spieltags
    python update.py --nur-webseite   nur die Webseite aus der vorhandenen Datenbank neu bauen
    python update.py                  fragt alles nacheinander ab

Neue Pokalrunde auslosen oder neue Saison anlegen bleibt bewusst ein eigener Schritt
(run_me.py, Punkt 1 bzw. 4), weil du den Zeitpunkt selbst bestimmst.
"""
import argparse
import sys

sys.path.append("./")
from scripts import (utils, league_system_database_filler, league_system_table_creator,
                     league_system_kbl_cup, kbl_score, build_site, spieltag_extras)

SYSTEMS = utils.alle_systeme()   # alle config/<system>.json, z. B. kbl, kwbl


def ask(prompt, valid=None, cast=str):
    while True:
        value = input(prompt).strip().lower()
        try:
            value = cast(value)
        except ValueError:
            print("❌ Ungueltige Eingabe.")
            continue
        if valid is None or value in valid:
            return value
        print(f"❌ Bitte eines davon eingeben: {', '.join(map(str, valid))}")


def run(system, matchday, cup=False, images=True, extras=True, website=True):
    season = utils.get_current_season(system)
    first, last = int(season["first_matchday"]), int(season["last_matchday"])
    if not (first <= matchday <= last):
        sys.exit(f"❌ Spieltag {matchday} liegt nicht in Saison {season['name']} ({first}-{last}).")
    md_kbl = utils.get_kbl_matchday(matchday, season["name"], system)

    print(f"\n1/4 📥 Daten holen: {system.upper()} {season['name']}, Bundesliga-Spieltag {matchday} (= {system.upper()}-Spieltag {md_kbl})")
    league_system_database_filler.fill_database(system, matchday, season)

    if cup:
        print("\n   🏆 Pokalrunde auswerten")
        league_system_kbl_cup.get_round_results(system, season["name"], matchday)

    if extras:
        print("\n   ⚽ Kaderwerte, Aufstellungen und Elfen des Spieltags")
        try:
            spieltag_extras.run(system, [matchday])
        except Exception as e:
            # Zusatzdaten duerfen das eigentliche Update nie aufhalten
            print(f"   ⚠️  Zusatzdaten uebersprungen: {e}")

    if images:
        print("\n2/4 🖼️  Tabellenbilder fuer alle Ligen")
        valid = utils.get_valid_league_names(system)
        config = utils.read_json(f"config/{system}")
        for league in config["leagues"]:
            for name in league["names"]:
                if name in valid:
                    league_system_table_creator.generate_matchday_tables(system, season["name"], md_kbl, name)
        print("\n3/4 📊 KBL-Score")
        kbl_score.main(system)
    else:
        print("\n2/4 + 3/4 uebersprungen (--ohne-bilder); KBL-Score wird nur in der Datenbank aktualisiert")
        kbl_score.update_kbl_score(system)

    if website:
        print("\n4/4 🌐 Webseite")
        build_site.main(SYSTEMS)
        print("\n✅ Fertig. Webseite liegt im Ordner docs/ – zum Veroeffentlichen siehe README.")


def main():
    p = argparse.ArgumentParser(description="KBL: Spieltag einspielen und alles neu erzeugen")
    p.add_argument("system", nargs="?", choices=SYSTEMS)
    p.add_argument("spieltag", nargs="?", type=int, help="Bundesliga-Spieltag (wie bisher)")
    p.add_argument("--pokal", action="store_true", help="Pokalrunde mit diesem Spieltag auswerten")
    p.add_argument("--ohne-bilder", action="store_true", help="keine JPEG-Tabellen erzeugen")
    p.add_argument("--nur-webseite", action="store_true", help="nur docs/ neu bauen")
    p.add_argument("--ohne-extras", action="store_true", help="keine Kaderwerte/Aufstellungen/Elfen holen")
    a = p.parse_args()

    if a.nur_webseite:
        build_site.main(SYSTEMS)
        return

    system = a.system or ask("❓ Welches Ligasystem? (%s): " % "/".join(SYSTEMS), SYSTEMS)
    season = utils.get_current_season(system)
    matchday = a.spieltag
    if matchday is None:
        matchday = ask(f"❓ Welcher Bundesliga-Spieltag? ({season['first_matchday']}-{season['last_matchday']}): ",
                       range(int(season["first_matchday"]), int(season["last_matchday"]) + 1), int)
        if not a.pokal:
            a.pokal = ask("❓ Pokalrunde mit diesem Spieltag auswerten? (j/n): ", ["j", "n"]) == "j"
    run(system, matchday, cup=a.pokal, images=not a.ohne_bilder, extras=not a.ohne_extras)


if __name__ == "__main__":
    main()
