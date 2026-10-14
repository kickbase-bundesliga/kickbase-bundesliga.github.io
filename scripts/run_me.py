import os
import sys
sys.path.append("./")
from scripts import league_system_manager, league_system_database_filler, league_system_table_creator, league_system_kbl_cup, build_site

# Number emoji map
number_emojis = {
    "1": "1️⃣",
    "2": "2️⃣",
    "3": "3️⃣",
    "4": "4️⃣",
    "5": "5️⃣"
}

# Mapping numbers to modules and descriptions
script_options = {
    "1": {
        "module": league_system_manager,
        "description": "Call right before the start of a new season to add new managers or create a new league system"
    },
    "2": {
        "module": league_system_database_filler,
        "description": "Call after matchday points are fixed to add data to the database"
    },
    "3": {
        "module": league_system_table_creator,
        "description": "Call to generate any kind of tables as image files"
    },
    "4": {
        "module": league_system_kbl_cup,
        "description": "Call to handle anything regarding the cup"
    },
    "5": {
        "module": build_site,
        "description": "Webseite (Ordner docs/) aus der Datenbank neu bauen"
    }
}

print("📜 Available scripts:")
for number, val in script_options.items():
    # Strip 'scripts.' prefix by just using module.__name__.split('.')[-1]
    script_name = val["module"].__name__.split('.')[-1]
    emoji = number_emojis[number]
    print(f"{emoji} {script_name} → {val['description']}")

# User prompt with emojis
while True:
    selection = input(f"❓ Which script do you want to run? (1/2/3/4/5): ").strip()
    # Convert emoji input back to number if user uses emoji
    if selection in number_emojis.values():
        # get the number key for that emoji
        selection = [k for k, v in number_emojis.items() if v == selection][0]

    if selection in script_options:
        selected_module = script_options[selection]["module"]
        print(f"✅ Selected script: {selected_module.__name__.split('.')[-1]}")
        break
    else:
        print(f"❌ Invalid input. Please enter (1/2/3/4/5).")

# Backup file check
league_systems_dir = "league_systems"
warning_limit = 10
warned_folders = []

for root, dirs, files in os.walk(league_systems_dir):
    if any(folder in root for folder in ["databases", "cup"]):
        backup_files = [f for f in files if "_backup_" in f]
        if len(backup_files) > warning_limit:
            warned_folders.append((root, len(backup_files)))

if warned_folders:
    print("⚠️  Warning: Too many backup files found in the following folders:")
    for folder, count in warned_folders:
        print(f"   ➤ {folder} ({count} backup files)")
    print("💡 Consider deleting old backups.")
else:
    pass

# Run the selected script's main function
if hasattr(selected_module, "main") and callable(selected_module.main):
    print(f"🚀 Running {selected_module.__name__.split('.')[-1]}.main()")
    if selected_module is build_site:
        build_site.main(build_site.SYSTEMS)
    else:
        selected_module.main()
else:
    print(f"❌ The selected script '{selected_module.__name__.split('.')[-1]}' does not have a callable main() function.")