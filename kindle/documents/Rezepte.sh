#!/bin/sh
# Name: Rezepte
# Author: Kuechen-Dashboard
# Icon: /mnt/us/extensions/kuechendash/rezepte.png
# DontUseFBInk
# Liegt in documents/ und erscheint ueber die Shell-Integration des Hotfix als „Rezepte“ in der Bibliothek.
# Oeffnet die Rezept-Seite fuer den Kindle im Browser (/kindle, immer aktuell vom Server). Ohne WLAN oder Server
# oeffnet es wie frueher still das letzte Rezeptbuch in KOReader (bis das Rezeptbuch abgeschafft ist, ideen.md).

DIR=${DIR:-/mnt/us/extensions/kuechendash}
ZIEL=${ZIEL:-/mnt/us/rezepte}
KOREADER=${KOREADER:-/mnt/us/koreader/koreader.sh}
FBINK=${FBINK:-/mnt/us/libkh/bin/fbink}
. "$DIR/einstellungen.sh"

log() { echo "$(date '+%d.%m. %H:%M:%S') $*" >> "$DIR/dash.log"; }
melden() { "$FBINK" -q -m -y -5 "$*"; }
wlan() { lipc-get-prop com.lab126.wifid cmState; }

melden "Rezepte werden geoeffnet ..."
# Direkt nach dem Aufwecken verbindet sich das WLAN noch (PENDING): wie in rezeptbuch.sh bis 40 s warten
t0=$(date +%s)
if [ "$(lipc-get-prop com.lab126.cmd wirelessEnable)" = 1 ] && [ "$(wlan)" != CONNECTED ]; then
  melden "Warte auf WLAN (hoechstens 40 s) ..."
  while [ "$(wlan)" != CONNECTED ] && [ $(($(date +%s) - t0)) -lt 40 ]; do sleep 1; done
fi
warten=$(($(date +%s) - t0))

curl -s -f --connect-timeout 5 -m 15 -o /dev/null "$SERVER/kindle"; rc=$?  # sonst zeigte der Browser nur einen Fehler
if [ "$rc" = 0 ]; then
  log "Rezepte im Browser geoeffnet (WLAN-Wartezeit ${warten} s)"
  # So oeffnet auch Amazons eigener Code auf dem Kindle den Browser (Sicherung vom 03.11.: com.lab126.browser?view=)
  exec lipc-set-prop com.lab126.appmgrd start "app://com.lab126.browser?view=$SERVER/kindle"
fi
buch=$ZIEL/rezeptbuch.epub
[ -f "$buch" ] || buch=$ZIEL  # noch kein Buch: KOReader zeigt den leeren Ordner
log "Rezepte: Server nicht erreichbar (curl $rc, WLAN $(wlan) nach ${warten} s), letztes Rezeptbuch in KOReader"
exec "$KOREADER" --kual --asap "$buch"  # dieselben Schalter wie der frueher genutzte „KOReader ASAP“
