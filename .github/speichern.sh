#!/usr/bin/env bash
# Neue Daten committen und pushen (mit Wiederholung, falls parallel etwas gespeichert wurde).
# Aufruf: bash .github/speichern.sh "Commit-Nachricht"   ->  setzt geaendert=true/false fuer GitHub
set -u
git config user.name  "kbl-automatik"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
for d in league_systems config; do [ -e "$d" ] && git add -A "$d"; done
if git diff --cached --quiet; then
  echo "Keine neuen Daten."
  echo "geaendert=false" >> "$GITHUB_OUTPUT"
  exit 0
fi
git commit -q -m "$1"
for i in 1 2 3 4 5; do
  if git pull --rebase --autostash -q && git push -q; then
    echo "geaendert=true" >> "$GITHUB_OUTPUT"
    exit 0
  fi
  sleep $((i * 5))
done
echo "::error::Speichern (push) fehlgeschlagen"
exit 1
