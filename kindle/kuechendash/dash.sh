#!/bin/sh
# Kuechen-Dashboard fuer den Kindle PW1: zeigt im Schlafbildschirm ein Bild vom Server
# und weckt sich zum Aktualisieren selbst. Start und Stopp per KUAL, kein Autostart.
# Der Ablauf ist auf einem Paperwhite 1 mit Firmware 5.6.1.1 erprobt.

DIR=${DIR:-/mnt/us/extensions/kuechendash}
FBINK=${FBINK:-/mnt/us/libkh/bin/fbink}
TMPD=${TMPD:-/tmp}
. "$DIR/einstellungen.sh"
LOG=$DIR/dash.log
LOCK=$TMPD/kuechendash.lock
FIFO=$TMPD/kuechendash.fifo
UMSCHALT=$TMPD/kuechendash.wlan-aus  # existiert nur, solange das WLAN fuers Umschalten aus ist
BILD=$TMPD/kuechendash.png
PROC=${PROC:-/proc}

log() { echo "$(date '+%d.%m. %H:%M:%S') $*" >> "$LOG"; }
melden() { "$FBINK" -q -m -y -5 "$*"; }
state() { lipc-get-prop com.lab126.powerd state; }
wlan() { lipc-get-prop com.lab126.wifid cmState; }
funk() { lipc-get-prop com.lab126.cmd wirelessEnable; }

holen() {  # $1 = Anlass; zeichnet nur, solange niemand den Kindle benutzt
  akku=$(lipc-get-prop com.lab126.powerd battLevel)
  if curl -s -f -m 20 -o "$TMPD/kuechendash-neu.png" "$SERVER/kueche.png?anlass=$1&akku=$akku"; then
    mv "$TMPD/kuechendash-neu.png" "$BILD"
    s=$(curl -s -f -m 10 "$SERVER/schlaf")
    case "$s" in ''|*[!0-9]*) s=1800 ;; esac
    [ "$s" -lt 60 ] && s=60
    schlaf=$s; fehler=0
    log "Bild $1 geholt, Akku $akku %, naechstes in ${schlaf}s"
  else
    rc=$?
    nochmal
    log "Abruf $1 fehlgeschlagen (curl $rc, WLAN $(wlan)), naechster Versuch in ${schlaf}s"
  fi
  [ -f "$BILD" ] && [ "$(state)" != active ] && "$FBINK" -q -c -f -g file="$BILD"
}

wlan_an() {  # nach dem Wecken im Schlafbildschirm kommt das WLAN nur durch kurzes Aus- und Einschalten
  [ "$(funk)" = 1 ] || { log "WLAN ist ausgeschaltet, kein Abruf"; return 1; }
  : > "$UMSCHALT"
  lipc-set-prop -i com.lab126.cmd wirelessEnable 0
  sleep 2
  lipc-set-prop -i com.lab126.cmd wirelessEnable 1 || lipc-set-prop -i com.lab126.cmd wirelessEnable 1
  rm -f "$UMSCHALT"
  # 30 s reichten am 03.11. zweimal nicht. Nach dem Wecken bleiben ~110 s bis zum Einschlafen,
  # 60 s WLAN plus 30 s curl passen also noch, bevor der Wecker neu gesetzt werden muss.
  t0=$(date +%s)
  while [ $(($(date +%s) - t0)) -lt 60 ]; do
    [ "$(wlan)" = CONNECTED ] && { log "WLAN nach $(($(date +%s) - t0)) s"; return 0; }
    sleep 2
  done
  log "WLAN kam nach dem Wecken nicht (nach 60 s: $(wlan))"
  return 1
}

nochmal() {  # WLAN klemmt zu Hause manchmal einmal (04./05.11.): bald neu versuchen, erst nach 3 Fehlern nur alle 3 h (unterwegs)
  fehler=$((fehler + 1))
  if [ "$fehler" -le 3 ]; then schlaf=600; else schlaf=10800; fi
}

wecker() {  # muss bei jedem readyToSuspend neu gesetzt werden, sonst weckt er nicht
  lipc-set-prop -i com.lab126.powerd rtcWakeup "$schlaf" 2>/dev/null && return
  lipc-set-prop -i com.lab126.powerd rtcWakeup 3600 2>/dev/null
  log "Wecker $schlaf abgelehnt, 3600 gesetzt"
}

lauf() {
  exec 9>"$LOCK"
  flock -n 9 || exit 0
  trap '' HUP
  [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 100000 ] && mv "$LOG" "$LOG.1"
  rm -f "$FIFO"; mkfifo "$FIFO"
  lipc-wait-event -m com.lab126.powerd '*' > "$FIFO" 2>/dev/null & LP=$!
  log "Dashboard an, Server $SERVER"
  schlaf=1800; fehler=0
  while read -r ev rest; do
    case "$ev" in
      goingToScreenSaver) sleep 3; holen einschlafen ;;
      readyToSuspend) wecker ;;
      wakeupFromSuspend)
        if [ "$(state)" != active ]; then
          if wlan_an; then holen wecker; else nochmal; log "Naechster Versuch in ${schlaf}s"; fi
        fi ;;
    esac
  done < "$FIFO"
  kill "$LP" 2>/dev/null
  rm -f "$FIFO"
  log "Dashboard aus (Ereignisse beendet)"
}

# Der Daemon (erkannt am eindeutigen Namen seiner RAM-Kopie) und seine direkten Kinder, etwa der Zuhoerer.
# Auf $! und auf "ls -l /proc/*/fd" war auf dem Kindle kein Verlass: beides fand den Daemon am 03.11. nicht.
unsere_prozesse() {
  daemon=""
  for p in "$PROC"/[0-9]*; do
    tr '\0' ' ' < "$p/cmdline" 2>/dev/null | grep -q 'kuechendash-lauf\.sh' && daemon="$daemon ${p##*/}"
  done
  [ -n "$daemon" ] || return 0
  echo $daemon
  for p in "$PROC"/[0-9]*; do
    s=$(cat "$p/stat" 2>/dev/null) || continue
    s=${s##*) }; set -- $s  # nach dem Programmnamen: Zustand, Elternprozess, ...
    case " $daemon " in *" $2 "*) echo "${p##*/}" ;; esac
  done
}

case "$1" in
  start)
    if ! flock -n 9 9>"$LOCK"; then melden "Dashboard laeuft schon"; exit 0; fi
    # Von einer Kopie im RAM laufen: USB-Modus und Updates der Datei stoeren dann nicht.
    cp "$0" "$TMPD/kuechendash-lauf.sh"
    /bin/sh "$TMPD/kuechendash-lauf.sh" lauf </dev/null >/dev/null 2>&1 &
    melden "Dashboard an - zum Anzeigen Kindle sperren"
    ;;
  stop)
    pids=$(unsere_prozesse)
    if [ -z "$pids" ]; then
      if flock -n 9 9>"$LOCK"; then melden "Dashboard war schon aus"; exit 0; fi
      log "Stopp: Sperre belegt, aber kein Prozess gefunden. $(busybox 2>&1 | head -1)"
      ps 2>&1 | grep -E 'kuechendash|lipc-wait' | grep -v grep >> "$LOG"
      melden "Dashboard laesst sich nicht stoppen - Kindle neu starten"
      exit 0
    fi
    for x in $pids; do log "Stopp: $x $(tr '\0' ' ' < "$PROC/$x/cmdline" 2>/dev/null)"; done
    kill $pids 2>/dev/null
    sleep 2
    rest=$(unsere_prozesse)
    [ -n "$rest" ] && kill -9 $rest 2>/dev/null
    # Mitten im WLAN-Umschalten gestoppt: wieder einschalten, sonst bliebe es aus.
    [ -f "$UMSCHALT" ] && { lipc-set-prop -i com.lab126.cmd wirelessEnable 1; rm -f "$UMSCHALT"; log "WLAN nach Stopp wieder eingeschaltet"; }
    rm -f "$FIFO"
    log "Dashboard aus (beendet: $(echo $pids)${rest:+, hart: $(echo $rest)})"
    if [ -n "$(unsere_prozesse)" ]; then melden "Dashboard laesst sich nicht stoppen - Kindle neu starten"; else melden "Dashboard aus"; fi
    ;;
  lauf) lauf ;;
esac
