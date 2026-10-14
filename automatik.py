"""
Automatisches Update eines Ligasystems - fuer GitHub (laeuft dort taeglich), geht aber auch lokal.

    python automatik.py kbl --pruefen     nur anzeigen, was passieren wuerde (aendert nichts)
    python automatik.py kbl               alle fertigen, noch nicht verarbeiteten Spieltage einspielen
    python automatik.py kbl --spieltag 6  genau diesen Bundesliga-Spieltag (neu) einspielen
          zusaetzlich: --pokal  --ohne-bilder  --ohne-extras  --ohne-webseite

Woran erkennt das Skript, dass ein Spieltag fertig ist?
  - Es holt den Spielplan des Wettbewerbs bei Kickbase (Bundesliga, Frauen-Bundesliga, ...).
  - Ein Spieltag gilt als fertig, wenn der Anstoss des letzten Spiels mindestens
    "wartezeit_stunden" (Standard 12) her ist. So sind auch spaete Korrekturen meist schon drin.
  - Nachholspiele (Anstoss erst nach Beginn des naechsten Spieltags) werden dabei nicht
    abgewartet, sonst wuerde alles stehen bleiben. Das Skript weist darauf hin; den Spieltag
    kann man spaeter mit --spieltag erneut einspielen.
  - Nachkontrolle: Ein eingespielter Spieltag wird an den beiden folgenden Tagen (ca. 24 und
    48 Std. spaeter) noch einmal geholt. Hat Kickbase Punkte nachtraeglich korrigiert, wird das
    uebernommen; sonst aendert sich nichts.
  - Welcher Spieltag zuletzt verarbeitet wurde, steht in league_systems/<system>/automatik_status.json.
    Fehlt die Datei, wird es aus der Datenbank abgeleitet.

Einstellungen in config/<system>.json (alles optional):
    "automatik": {"wettbewerb": 1, "wartezeit_stunden": 12, "nachkontrolle_stunden": 50}
        wettbewerb = Kickbase-Wettbewerbsnummer (wird sonst aus den Ligadaten gelesen)
        nachkontrolle_stunden = wie lange nach dem Einspielen erneut geholt wird (0 = aus)

Der Pokal wird NIE automatisch ausgewertet, nur von Hand:
    python automatik.py kbl --spieltag 6 --pokal
holt Spieltag 6 frisch von Kickbase (also mit endgueltigen Punkten) und wertet dann die
aktuelle Pokalrunde aus. Erst starten, wenn Kickbase den Spieltag abgeschlossen hat
(meist am Tag nach dem letzten Spiel gegen 18 Uhr).

Neue Saison anlegen und Pokal auslosen bleiben bewusst Handarbeit (run_me.py).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.append("./")
from scripts import utils  # noqa: E402

MAX_SPIELTAGE_PRO_LAUF = 5
# Kickbase-Wettbewerbe: 1 Bundesliga, 2 2. Bundesliga, 3 La Liga, 4 Frauen-Bundesliga
STANDARD_WETTBEWERB = {"kbl": 1, "k2bl": 2, "laliga": 3, "kwbl": 4}


# ---------------------------------------------------------------- Ausgabe

class Bericht:
    """Sammelt Meldungen fuer die Konsole und - auf GitHub - fuer die Zusammenfassung des Laufs."""

    def __init__(self, system):
        self.system = system
        self.zeilen = []

    def __call__(self, text=""):
        print(text)
        self.zeilen.append(text)

    def speichern(self):
        ziel = os.environ.get("GITHUB_STEP_SUMMARY")
        if not ziel:
            return
        with open(ziel, "a", encoding="utf-8") as f:
            f.write("## %s\n\n" % self.system.upper())
            for z in self.zeilen:
                f.write((z.strip() or "") + "  \n")
            f.write("\n")


# ---------------------------------------------------------------- Zeit / Spielplan

def jetzt():
    return datetime.now(timezone.utc)


def zeit_lesen(text):
    """Kickbase-Zeitangaben wie 2026-10-17T13:30:00Z oder ...00.000+02:00 -> datetime (UTC)."""
    if not isinstance(text, str) or len(text) < 19 or text[4] != "-":
        return None
    t = text.strip().replace("Z", "+00:00")
    haupt, rest = t[:19], t[19:]
    if rest.startswith("."):                       # Sekundenbruchteile weglassen
        i = 1
        while i < len(rest) and rest[i].isdigit():
            i += 1
        rest = rest[i:]
    try:
        d = datetime.strptime(haupt, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None
    if rest and rest[0] in "+-" and len(rest) >= 6:
        vz = 1 if rest[0] == "+" else -1
        versatz = timedelta(hours=int(rest[1:3]), minutes=int(rest[4:6]))
        return (d - vz * versatz).replace(tzinfo=timezone.utc)
    return d.replace(tzinfo=timezone.utc)


def spielplan_lesen(antwort):
    """Antwort von /competitions/<nr>/matchdays -> {Spieltag: [Anstosszeiten]}.
    Bewusst tolerant: sucht ueberall nach Objekten mit Anstosszeit 'dt' und Spieltag 'day'."""
    plan = {}

    def tag_von(obj, geerbt):
        for k in ("day", "md", "mdn"):
            v = obj.get(k)
            if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
                return int(v)
        return geerbt

    def gehen(obj, tag):
        if isinstance(obj, list):
            for x in obj:
                gehen(x, tag)
        elif isinstance(obj, dict):
            tag = tag_von(obj, tag)
            zeit = zeit_lesen(obj.get("dt"))
            if zeit is not None and tag is not None:
                plan.setdefault(tag, []).append(zeit)
            for v in obj.values():
                if isinstance(v, (list, dict)):
                    gehen(v, tag)

    gehen(antwort, None)
    return {t: sorted(z) for t, z in plan.items()}


def spieltag_status(plan, tag, wartezeit, now):
    """-> (fertig: bool, info: str, nachholspiele: [datetime])"""
    zeiten = plan.get(tag)
    if not zeiten:
        return False, "Spieltag %d nicht im Spielplan gefunden" % tag, []
    naechster = plan.get(tag + 1)
    beginn_naechster = naechster[0] if naechster else None
    regulaer = [z for z in zeiten if beginn_naechster is None or z < beginn_naechster]
    nachhol = [z for z in zeiten if z not in regulaer]
    if not regulaer:                      # sollte nicht vorkommen - dann alles abwarten
        regulaer, nachhol = zeiten, []
    letzter = regulaer[-1]
    bereit_ab = letzter + wartezeit
    if now >= bereit_ab:
        return True, "letztes Spiel %s, fertig seit %s" % (berlin(letzter), berlin(bereit_ab)), nachhol
    return False, "letztes Spiel %s, wird verarbeitet ab %s" % (berlin(letzter), berlin(bereit_ab)), nachhol


def berlin(d):
    """Grobe Anzeige in deutscher Zeit (Sommerzeit Ende Maerz bis Ende Oktober)."""
    jahr = d.year
    def letzter_sonntag(monat):
        t = datetime(jahr, monat, 31, 1, tzinfo=timezone.utc)
        return t - timedelta(days=(t.weekday() + 1) % 7)
    sommer = letzter_sonntag(3) <= d < letzter_sonntag(10)
    lokal = d + timedelta(hours=2 if sommer else 1)
    tage = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
    return "%s %s Uhr" % (tage[lokal.weekday()], lokal.strftime("%d.%m. %H:%M"))


# ---------------------------------------------------------------- Status

def status_pfad(system):
    return os.path.join("league_systems", system, "automatik_status.json")


def letzter_verarbeiteter(system, saison):
    """Bundesliga-Spieltag, der zuletzt eingespielt wurde (first_matchday - 1 = noch keiner)."""
    erster = int(saison["first_matchday"])
    st = status_lesen(system, saison)
    if "letzter_spieltag" in st:
        return int(st["letzter_spieltag"]), "Statusdatei"
    # Aus der Datenbank: hoechster KBL-Spieltag mit Punkten in dieser Saison
    db = utils.read_json("league_systems/%s/databases/%s_database" % (system, system))
    hoechster = 0
    for daten in db.values():
        s = daten.get(saison["name"]) if isinstance(daten, dict) else None
        if not isinstance(s, dict):
            continue
        for i, p in enumerate(s.get("MdPoints") or []):
            if i > hoechster and p:
                hoechster = i
    return erster + hoechster - 1, "Datenbank"


def status_lesen(system, saison):
    pfad = status_pfad(system)
    if os.path.exists(pfad):
        with open(pfad, encoding="utf-8") as f:
            st = json.load(f)
        if st.get("saison") == saison["name"]:
            return st
    return {}


def status_schreiben(system, saison, spieltag, eingespielt):
    """eingespielt: Bundesliga-Spieltag, der gerade (neu) eingespielt wurde -> fuer die Nachkontrolle."""
    alt = status_lesen(system, saison)
    zeiten = dict(alt.get("eingespielt_am") or {})
    zeiten[str(eingespielt)] = jetzt().strftime("%Y-%m-%dT%H:%M:%SZ")
    # nur die letzten Spieltage merken
    behalten = sorted(zeiten, key=int)[-3:]
    with open(status_pfad(system), "w", encoding="utf-8") as f:
        json.dump({"saison": saison["name"], "letzter_spieltag": spieltag,
                   "eingespielt_am": {k: zeiten[k] for k in behalten}}, f, indent=2)
        f.write("\n")


def nachkontrolle_faellig(system, saison, fenster, now):
    """Spieltage, die vor 20 Std. bis <fenster> eingespielt wurden -> erneut holen.
    Bei taeglichem Lauf heisst das: ca. 24 und 48 Std. nach dem ersten Einspielen."""
    faellig = []
    for tag, wann in (status_lesen(system, saison).get("eingespielt_am") or {}).items():
        t = zeit_lesen(wann)
        if t is not None and timedelta(hours=20) <= now - t <= fenster:
            faellig.append(int(tag))
    return sorted(faellig)


def daten_fingerabdruck(system):
    """Pruefsumme ueber Datenbank und Zusatzdaten -> erkennt, ob sich etwas geaendert hat."""
    import hashlib
    h = hashlib.sha1()
    for ordner in ("databases", "extras"):
        pfad = os.path.join("league_systems", system, ordner)
        if not os.path.isdir(pfad):
            continue
        for fn in sorted(os.listdir(pfad)):
            if "_backup_" in fn or not fn.endswith(".json"):
                continue
            with open(os.path.join(pfad, fn), "rb") as f:
                h.update(fn.encode() + f.read())
    return h.hexdigest()


# ---------------------------------------------------------------- Kickbase

def wettbewerb_ermitteln(system, config, api):
    einst = config.get("automatik") or {}
    if einst.get("wettbewerb"):
        return int(einst["wettbewerb"]), "config"
    # Aus den Ligadaten des Admin-Accounts: Feld cpi (= Wettbewerb) einer Liga dieses Systems
    namen = set(n for lc in config.get("leagues", []) for n in lc.get("names", []))
    gefunden = []

    def suchen(obj):
        if isinstance(obj, list):
            for x in obj:
                suchen(x)
        elif isinstance(obj, dict):
            name = obj.get("n") or obj.get("nm") or obj.get("name") or obj.get("lnm")
            if name in namen and obj.get("cpi") is not None:
                gefunden.append(obj.get("cpi"))
            for v in obj.values():
                if isinstance(v, (list, dict)):
                    suchen(v)

    suchen(getattr(api, "login_antwort", {}))
    if gefunden:
        try:
            return int(gefunden[0]), "Ligadaten"
        except (TypeError, ValueError):
            pass
    if system in STANDARD_WETTBEWERB:
        return STANDARD_WETTBEWERB[system], "Standard"
    raise SystemExit("❌ Wettbewerb fuer %s unbekannt. Bitte in config/%s.json eintragen: "
                     "\"automatik\": {\"wettbewerb\": <Nummer>}" % (system.upper(), system))


# ---------------------------------------------------------------- Ablauf

def main():
    systeme = utils.alle_systeme()
    p = argparse.ArgumentParser(description="Fertige Spieltage automatisch einspielen")
    p.add_argument("system", choices=systeme)
    p.add_argument("--pruefen", action="store_true", help="nur anzeigen, nichts aendern")
    p.add_argument("--spieltag", type=int, help="genau diesen Bundesliga-Spieltag einspielen")
    p.add_argument("--pokal", action="store_true", help="mit --spieltag: Pokalrunde auswerten")
    p.add_argument("--ohne-bilder", action="store_true")
    p.add_argument("--ohne-extras", action="store_true")
    p.add_argument("--ohne-webseite", action="store_true", help="docs/ nicht neu bauen")
    a = p.parse_args()

    system = a.system
    log = Bericht(system)
    try:
        ergebnis = ablauf(system, a, log)
    finally:
        log.speichern()
    return ergebnis


def ablauf(system, a, log):
    config = utils.read_json("config/" + system)
    saison = utils.get_current_season(system)
    erster, letzter = int(saison["first_matchday"]), int(saison["last_matchday"])
    einst = config.get("automatik") or {}
    wartezeit = timedelta(hours=float(einst.get("wartezeit_stunden", 12)))
    fenster = timedelta(hours=float(einst.get("nachkontrolle_stunden", 50)))

    log("Saison %s, Bundesliga-Spieltage %d-%d" % (saison["name"], erster, letzter))

    # --- Manuell: genau ein Spieltag
    if a.spieltag is not None:
        if not (erster <= a.spieltag <= letzter):
            raise SystemExit("❌ Spieltag %d liegt nicht in Saison %s (%d-%d)."
                             % (a.spieltag, saison["name"], erster, letzter))
        pokal = a.pokal
        log("Manuell: Spieltag %d%s" % (a.spieltag, " mit Pokalrunde" if pokal else ""))
        if a.pruefen:
            log("(nur Pruefung - nichts geaendert)")
            return 0
        bisher, _ = letzter_verarbeiteter(system, saison)
        einspielen(system, saison, a.spieltag, pokal, a, log)
        status_schreiben(system, saison, max(bisher, a.spieltag), a.spieltag)
        webseite(a, log)
        return 0

    if a.pokal:
        raise SystemExit("❌ Pokal nur zusammen mit einem Spieltag: --spieltag <Nr> --pokal")

    # --- Automatisch (ohne Pokal): was ist fertig und noch offen?
    bisher, quelle = letzter_verarbeiteter(system, saison)
    log("Zuletzt eingespielt: Spieltag %s (laut %s)" % (bisher if bisher >= erster else "keiner", quelle))

    # Nachkontrolle: kuerzlich eingespielte Spieltage erneut holen (spaete Punktkorrekturen von Kickbase)
    geaendert = False
    nachkontrolle = nachkontrolle_faellig(system, saison, fenster, jetzt())
    for tag in nachkontrolle:
        if a.pruefen:
            log("🔁 Wuerde Spieltag %d zur Nachkontrolle erneut holen" % tag)
            continue
        vorher = daten_fingerabdruck(system)
        log("🔁 Nachkontrolle Spieltag %d (spaete Korrekturen von Kickbase)" % tag)
        import update
        update.run(system, tag, cup=False, images=not a.ohne_bilder,
                   extras=not a.ohne_extras, website=False)
        if daten_fingerabdruck(system) != vorher:
            log("✏️  Spieltag %d: Kickbase hat nachtraeglich etwas geaendert - uebernommen." % tag)
            geaendert = True
        else:
            log("✔️  Spieltag %d: keine Aenderungen." % tag)

    if bisher >= letzter:
        log("✅ Saison %s ist komplett eingespielt. Naechster Schritt: neue Saison anlegen (run_me.py)."
            % saison["name"])
        if geaendert:
            webseite(a, log)
        return 0

    from scripts.spieltag_extras import Api
    api = Api(system)
    wettbewerb, herkunft = wettbewerb_ermitteln(system, config, api)
    antwort = api.get("/competitions/%d/matchdays" % wettbewerb)
    plan = spielplan_lesen(antwort)
    log("Spielplan: Wettbewerb %d (%s), %d Spieltage gefunden" % (wettbewerb, herkunft, len(plan)))
    if not plan:
        os.makedirs("api_dump", exist_ok=True)
        with open(os.path.join("api_dump", "spielplan_%s.json" % system), "w", encoding="utf-8") as f:
            json.dump(antwort, f, ensure_ascii=False, indent=2)
        raise SystemExit("❌ Spielplan konnte nicht gelesen werden (Antwort in api_dump/spielplan_%s.json)."
                         % system)

    now = jetzt()
    offen = []
    for tag in range(max(bisher + 1, erster), letzter + 1):
        fertig, info, nachhol = spieltag_status(plan, tag, wartezeit, now)
        zeile = "Spieltag %d: %s" % (tag, info)
        if nachhol:
            zeile += " – Nachholspiel(e): " + ", ".join(berlin(z) for z in nachhol)
        log(("✔️  " if fertig else "⏳ ") + zeile)
        if not fertig:
            break
        offen.append((tag, nachhol))

    if not offen:
        log("Keine neuen Spieltage.")
        if geaendert:
            webseite(a, log)
        return 0
    if len(offen) > MAX_SPIELTAGE_PRO_LAUF:
        log("⚠️  %d Spieltage offen - verarbeite in diesem Lauf nur die ersten %d."
            % (len(offen), MAX_SPIELTAGE_PRO_LAUF))
        offen = offen[:MAX_SPIELTAGE_PRO_LAUF]

    if a.pruefen:
        log("Wuerde einspielen: " + ", ".join(str(t) for t, _ in offen))
        log("(nur Pruefung - nichts geaendert)")
        return 0

    for tag, nachhol in offen:
        einspielen(system, saison, tag, False, a, log)
        status_schreiben(system, saison, tag, tag)
        if nachhol:
            log("ℹ️  Spieltag %d hat Nachholspiele. Falls deren Punkte noch zaehlen, spaeter "
                "erneut einspielen (Spieltag %d manuell)." % (tag, tag))
    webseite(a, log)
    return 0


def einspielen(system, saison, tag, pokal, a, log):
    import update
    log("▶️  Spieltag %d wird eingespielt%s" % (tag, " (mit Pokalrunde)" if pokal else ""))
    update.run(system, tag, cup=pokal, images=not a.ohne_bilder,
               extras=not a.ohne_extras, website=False)
    log("✅ Spieltag %d eingespielt" % tag)


def webseite(a, log):
    if a.ohne_webseite:
        return
    from scripts import build_site
    build_site.main(build_site.SYSTEMS)
    log("🌐 Webseite neu gebaut")


if __name__ == "__main__":
    sys.exit(main())
