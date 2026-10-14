# KickBase BundesLiga – Liga-Tools und Webseite

Daten, Auswertungen und Webseite für die Ligasysteme **KBL**, **KWBL** (und später weitere).
Die Spieltage laufen automatisch auf GitHub, können aber auch lokal eingespielt werden.

---

## Für Admins: Bedienung auf GitHub

Alles im Reiter **Actions** des Repositorys.

| Workflow | Was er tut |
|---|---|
| **KBL Spieltag** / **KWBL Spieltag** | Läuft jeden Morgen von selbst. Prüft, ob ein Bundesliga-Spieltag fertig ist, und spielt ihn ein (Daten, Pokal, KBL-Score, Webseite). |
| **Webseite** | Baut die Webseite neu und veröffentlicht sie. Läuft automatisch nach jeder Änderung. |
| **Pokal** | Pokal anlegen, Runden auslosen – auch als Live-Auslosung auf der Webseite. Nur per Knopf. |

**Von Hand starten:** Workflow anklicken → **Run workflow** →

- *Bundesliga-Spieltag*: leer lassen = automatisch erkennen, oder eine Nummer eintragen, um genau
  diesen Spieltag (erneut) einzuspielen, z. B. wenn Kickbase Punkte nachträglich korrigiert hat.
- *Pokalrunde auswerten*: Haken setzen **und** die Spieltagsnummer eintragen. Der Spieltag wird
  dann frisch von Kickbase geholt und danach die aktuelle Pokalrunde ausgewertet. Erst starten,
  wenn Kickbase den Spieltag abgeschlossen hat (meist am Tag nach dem letzten Spiel gegen 18 Uhr).
  **Der Pokal läuft nie automatisch.**
- *Nur prüfen*: zeigt nur an, was passieren würde.

**Ergebnis ansehen:** Den Lauf anklicken. Oben steht die Zusammenfassung (welche Spieltage fertig
sind, was eingespielt wurde). Ganz unten unter *Artifacts* liegen die **Tabellenbilder** als ZIP
zum Herunterladen (30 Tage).

### Pokal

Alles im Workflow **Pokal** → *Run workflow* → Ligasystem und Aktion wählen:

| Aktion | Was passiert |
|---|---|
| **Live-Auslosung terminieren** | Startzeit eintragen (z. B. `20:00` oder `20.10. 20:00`, deutsche Zeit, mindestens 15 Minuten und höchstens ca. 5 Stunden im Voraus). Die Webseite zeigt sofort ein Banner mit Countdown. Etwa 6 Minuten vor dem Start wird ausgelost und veröffentlicht; ab der Startzeit zieht die Webseite Kugel für Kugel aus dem Lostopf (Standard 5 Sekunden pro Kugel). Alle Besucher sehen dasselbe zur selben Zeit; danach lässt sich die Ziehung erneut abspielen. |
| **Runde sofort auslosen** | Wie bisher, ohne Show. |
| **Ankündigung zurücknehmen** | Banner weg. Vorher den laufenden Live-Lauf unter *Actions* abbrechen (*Cancel workflow*). |
| **Neuen Pokal anlegen** | Zum Saisonstart aus `league_systems/<system>/cup/<SYSTEM>Cup_Participants_<Saison>.csv`, sofort ohne Show. |

**Erste Runde live:** Gibt es für die aktuelle Saison noch keinen Pokal, legt *Live-Auslosung terminieren*
ihn an (Teilnehmerliste muss im Repository liegen). In der Show werden zuerst die Freilose einzeln
gezeigt (vergeben nach KBL-Score), danach die Paarungen gezogen. Dauer: Kugeln × Sekunden, bei
123 Teilnehmern und 5 Sekunden also gut 10 Minuten.

Reihenfolge pro Runde: Spieltag mit **Pokal-Haken** einspielen (Ergebnisse) → **auslosen**. Ausgelost
werden kann erst, wenn die Ergebnisse der laufenden Runde da sind; das wird vorab geprüft.
Das Paarungsbild liegt am jeweiligen Lauf unter *Artifacts*.

Hinweis: Die Paarungen stehen ein paar Minuten vor dem Start schon in den öffentlichen Daten.
Auf der Webseite sind sie bis zur Ziehung nicht zu sehen.

Lokal geht dasselbe mit `python pokal.py kbl neu | auslosen | ankuendigen --start 20:00 | live-ziehen | absagen`.

**Info-Texte ändern:** `config/kbl_info.txt` auf GitHub öffnen → Stift-Symbol → ändern →
*Commit changes*. Die Webseite aktualisiert sich danach von selbst.

### Wann gilt ein Spieltag als fertig?

- Der Anstoß des letzten Spiels ist mindestens 12 Stunden her (einstellbar, siehe unten).
- Nachholspiele (Anstoß erst nach Beginn des nächsten Spieltags) werden nicht abgewartet.
  Die Zusammenfassung weist darauf hin; wenn deren Punkte noch zählen, den Spieltag später
  per Hand mit seiner Nummer erneut einspielen.
- **Nachkontrolle:** Jeder Spieltag wird an den beiden folgenden Morgen (ca. 24 und 48 Stunden
  nach dem Einspielen) noch einmal geholt. Hat Kickbase Punkte nachträglich korrigiert, wird das
  übernommen und die Webseite aktualisiert; sonst ändert sich nichts. Der Pokal wird dabei nie
  angefasst.
- Der zuletzt eingespielte Spieltag steht in `league_systems/<system>/automatik_status.json`.
- Nach dem letzten Spieltag einer Saison passiert nichts mehr, bis die neue Saison angelegt ist.

Bewusst **Handarbeit** bleiben: neue Saison anlegen (`python scripts/run_me.py`) und alles rund um den
Pokal (Ergebnisse per Pokal-Haken, Auslosung über den Workflow **Pokal**).

---

## Lokal arbeiten (Windows, PowerShell)

> **Wichtig:** Vor lokaler Arbeit in GitHub Desktop immer erst **Fetch origin / Pull** klicken,
> danach **Commit** und **Push**. Nie gleichzeitig lokal und auf GitHub einen Spieltag einspielen.

```powershell
python automatik.py kbl --pruefen   # zeigt, welche Spieltage fertig sind (ändert nichts)
python automatik.py kbl             # spielt alle fertigen, offenen Spieltage ein
python update.py kbl 5              # wie bisher: Bundesliga-Spieltag 5 einspielen
python update.py kbl 5 --pokal      # dazu die Pokalrunde auswerten (nur von Hand)
python automatik.py kbl --spieltag 5 --pokal   # dasselbe über die Automatik
python update.py --nur-webseite     # nur die Webseite (Ordner docs/) neu bauen
python -m http.server -d docs       # Webseite ansehen: http://localhost:8000
```

Oder `update.bat` doppelklicken, dann wird alles abgefragt.

**Zugangsdaten** lokal wie bisher in `config/kbl.txt`, `config/kwbl.txt`
(Zeile 1 E-Mail, Zeile 2 Passwort, Zeile 3 Admin-ID). Diese Dateien werden nie hochgeladen
(siehe `.gitignore`). Auf GitHub kommen sie aus den **Secrets** (siehe unten).

---

## Einstellungen

In `config/<system>.json`:

```json
"automatik": {"wettbewerb": 1, "wartezeit_stunden": 12, "nachkontrolle_stunden": 50}
```

- `wettbewerb`: Kickbase-Wettbewerb (1 = Bundesliga). Fehlt die Angabe, wird er aus den Ligadaten gelesen.
- `wartezeit_stunden`: so lange nach dem Anstoß des letzten Spiels wird gewartet.
- `nachkontrolle_stunden`: so lange nach dem Einspielen wird täglich erneut geholt (0 = aus, Standard 50).

---

## Einrichtung auf GitHub (einmalig)

1. **Secrets** anlegen: Repository → *Settings* → *Secrets and variables* → *Actions* →
   *New repository secret*:
   - `KBL_EMAIL`, `KBL_PASSWORT`
   - `KWBL_EMAIL`, `KWBL_PASSWORT`

   Secrets sind verschlüsselt; niemand kann sie wieder ansehen, auch Mit-Admins nicht.
2. **Pages**: *Settings* → *Pages* → *Source*: **GitHub Actions**.
3. Unter *Actions* einmal **Webseite** → *Run workflow* starten.
4. Mit-Admins: in der Organisation einladen und dem Repository mit Rolle **Write** hinzufügen.

---

## Neues Ligasystem hinzufügen (z. B. K2BL, La Liga)

1. `config/<kuerzel>.json` anlegen (wie `kwbl.json`), mit `"automatik": {"wettbewerb": <Nr>}`.
   Ab dann erscheint das System automatisch auf der Webseite und in `update.py`.
2. `.github/workflows/kwbl.yml` kopieren als `<kuerzel>.yml` und darin `KWBL`/`kwbl` ersetzen
   (Name, `system:`, Secret-Namen) und die Uhrzeit beim `cron` um ein paar Minuten verschieben.
3. Secrets `<KUERZEL>_EMAIL` und `<KUERZEL>_PASSWORT` anlegen.
4. Lokal: `config/<kuerzel>.txt` mit den Zugangsdaten.

---

## Hintergrund

**Admin-Korrekturen:** Kickbase zählt Gutschriften vom Admin nur in den Gesamtpunkten. Die Korrektur
ist Gesamtpunkte minus Summe aller Spieltagspunkte; sie steht pro Saison unter `"Corrections"` und
wird in Tabellen (Spalte **Korr.**), Platzierung und Webseite eingerechnet. Pokalspiele werten nur
die Spieltagspunkte (mal Liga-Faktor).

**Ordner:**

- `league_systems/<system>/` – Datenbank, Pokale, Zusatzdaten (wird hochgeladen)
- `config/` – Einstellungen, Info-Texte, Datenlücken (Zugangsdateien bleiben lokal)
- `website/` – Vorlage der Webseite; `docs/` – fertige Webseite (nur lokal, wird online neu gebaut)
- `scripts/` – alle Werkzeuge; `automatik.py`, `update.py`, `pokal.py` – Einstiegspunkte
- `.github/workflows/` – die Abläufe auf GitHub
