#!/usr/bin/env bash
# Extract, update, and compile GNU gettext catalogs (Babel 2.17).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCALES="$ROOT/src/music_downloader/locales"
POT="$LOCALES/messages.pot"
cd "$ROOT"

pybabel extract -F babel.cfg -k _:1 -k ngettext:1,2 -o "$POT" src/music_downloader
for locale in es de gl; do
  po="$LOCALES/$locale/LC_MESSAGES/messages.po"
  if [[ -f "$po" ]]; then
    pybabel update -i "$POT" -d "$LOCALES" -D messages -l "$locale"
  else
    pybabel init -i "$POT" -d "$LOCALES" -D messages -l "$locale"
  fi
done
pybabel compile -d "$LOCALES" -D messages
