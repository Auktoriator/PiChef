#!/bin/sh
# Holt das Rezeptbuch (EPUB aus allen Rezepten) vom Server nach /mnt/us/rezepte/ fuer KOReader.
# Aufruf per KUAL oder aus documents/Rezepte.sh. Das alte Buch bleibt, wenn der Abruf scheitert.

DIR=${DIR:-/mnt/us/extensions/kuechendash}
FBINK=${FBINK:-/mnt/us/libkh/bin/fbink}
ZIEL=${ZIEL:-/mnt/us/rezepte}
LEISE=${LEISE:-}  # von Rezepte.sh gesetzt: nur „Warte auf WLAN“ zeigen, kein Ergebnis
. "$DIR/einstellungen.sh"
NEU=$ZIEL/.rezeptbuch.epub.neu  # Punkt vorn: KOReader blendet die halbe Datei aus

log() { echo "$(date '+%d.%m. %H:%M:%S') $*" >> "$DIR/dash.log"; }
melden() { "$FBINK" -q -m -y -5 "$*"; }
wlan() { lipc-get-prop com.lab126.wifid cmState; }

# Direkt nach dem Aufwecken verbindet sich das WLAN noch (PENDING). Am 03.11. reichten 16 s nicht,
# nach dem Wecken im Schlafbildschirm dauert es 29-32 s: deshalb bis 40 s warten
t0=$(date +%s)
if [ "$(lipc-get-prop com.lab126.cmd wirelessEnable)" = 1 ] && [ "$(wlan)" != CONNECTED ]; then
  melden "Warte auf WLAN (hoechstens 40 s) ..."
  while [ "$(wlan)" != CONNECTED ] && [ $(($(date +%s) - t0)) -lt 40 ]; do sleep 1; done
fi
warten=$(($(date +%s) - t0))

mkdir -p "$ZIEL"
curl -s -f --connect-timeout 5 -m 60 -o "$NEU" "$SERVER/rezeptbuch.epub"; rc=$?  # Pi aus: nach 5 s weiter
anfang=$(dd if="$NEU" bs=2 count=1 2>/dev/null)  # nicht head -c: das scheiterte am 03.11. auf dem Kindle
if [ "$rc" = 0 ] && [ "$anfang" = PK ]; then
  mv "$NEU" "$ZIEL/rezeptbuch.epub"
  log "Rezeptbuch geholt ($(wc -c < "$ZIEL/rezeptbuch.epub") Bytes, WLAN-Wartezeit ${warten} s)"
  [ -n "$LEISE" ] || melden "Rezeptbuch geholt - in KOReader unter rezepte"
else
  log "Rezeptbuch nicht geholt (curl $rc, Anfang '$anfang', WLAN $(wlan) nach ${warten} s)"
  rm -f "$NEU"
  if [ -n "$LEISE" ]; then :
  elif [ "$rc" = 0 ]; then melden "Rezeptbuch nicht geholt - Antwort war kein EPUB"
  else melden "Rezeptbuch nicht geholt - WLAN an?"; fi
fi
