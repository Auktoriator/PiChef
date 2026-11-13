#!/bin/sh
T=/t; S=$T/stubs
export PATH=$S:$PATH DIR=$T/ext TMPD=$T/tmp FBINK=$S/fbink
mkdir -p $TMPD; : > $T/queue; echo CONNECTED > $T/wlan; echo screenSaver > $T/state; echo 1 > $T/funk
q() { echo "$1" >> $T/queue; }
zeige() { echo "--- $1: daemon=$(ps | grep -c '[k]uechendash-lauf') zuhoerer=$(ps | grep -c '[t]ail -n 0 -f')"; }
sh $DIR/dash.sh start; sleep 1; zeige "nach Start"
q "goingToScreenSaver 2"; sleep 5
sh $DIR/dash.sh start; sleep 1; zeige "nach zweitem Start"
sh $DIR/dash.sh stop; zeige "nach Stopp"
sh $DIR/dash.sh start; sleep 1; zeige "nach neuem Start"
q "goingToScreenSaver 2"; sleep 5
echo NA > $T/wlan; q "wakeupFromSuspend"; sleep 1
sh $DIR/dash.sh stop; zeige "nach Stopp mitten im WLAN-Umschalten"
sh $DIR/dash.sh stop
echo 35 > $T/wlan-dauer; sh $DIR/dash.sh start; sleep 1  # WLAN langsamer als die alten 30 s
echo NA > $T/wlan; q "wakeupFromSuspend"; sleep 45; q "readyToSuspend 5"; sleep 1
echo 999 > $T/wlan-dauer; echo NA > $T/wlan; q "wakeupFromSuspend"; sleep 66; q "readyToSuspend 4"; sleep 1
sh $DIR/dash.sh stop; zeige "nach langsamem und klemmendem WLAN"
export ZIEL=$T/rezepte
echo CONNECTED > $T/wlan
sh $DIR/rezeptbuch.sh; echo "--- Rezeptbuch: $(cat $ZIEL/rezeptbuch.epub) | $(ls -A $ZIEL)"
echo html > $T/rezeptbuch; sh $DIR/rezeptbuch.sh; echo "--- nach Portal-Antwort: $(cat $ZIEL/rezeptbuch.epub) | $(ls -A $ZIEL)"
echo weg > $T/rezeptbuch; sh $DIR/rezeptbuch.sh; echo "--- Server weg: $(cat $ZIEL/rezeptbuch.epub) | $(ls -A $ZIEL)"
export KOREADER=$S/koreader.sh  # Eintrag „Rezepte“ aus documents/
echo "fbink ---- ab hier Rezepte.sh" >> $T/fbink.calls; echo "---- ab hier Rezepte.sh" >> $T/set.calls
echo ok > $T/rezeptbuch; echo PENDING > $T/wlan; ( sleep 4; echo CONNECTED > $T/wlan ) &  # gerade aufgeweckt
a=$(date +%s); sh $DIR/Rezepte.sh; echo "--- Rezepte, WLAN erst nach 4 s: $(($(date +%s) - a)) s"
echo 0 > $T/funk; echo NA > $T/wlan; echo weg > $T/rezeptbuch
a=$(date +%s); sh $DIR/Rezepte.sh; echo "--- Rezepte, WLAN aus: $(($(date +%s) - a)) s"
echo 1 > $T/funk; echo CONNECTED > $T/wlan
rm -rf $ZIEL; sh $DIR/Rezepte.sh; echo "--- Rezepte ohne Buch, Server weg"
echo "=== koreader"; cat $T/ko.calls
echo "=== dash.log"; cat $DIR/dash.log
echo "=== fbink"; cat $T/fbink.calls
echo "=== lipc-set-prop"; cat $T/set.calls
echo "funk am Ende=$(cat $T/funk)"
