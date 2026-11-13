# Zusatz: Kindle als Küchen-Display

Ein Kindle Paperwhite der ersten Generation zeigt im **Schlafbildschirm** ein Bild vom Server: Datum, Wetter,
„Heute kochen“ und die Einkaufsliste. Er bleibt normal zum Lesen nutzbar. Ein Eintrag „Rezepte“ in der Bibliothek
öffnet die Rezepte im Browser des Kindle.

**Auf eigene Gefahr.** Das läuft nur auf einem Kindle mit Jailbreak und ist an genau einem Gerät erprobt: Paperwhite 1,
Firmware 5.6.1.1. Andere Modelle verhalten sich beim Schlafen, Wecken und im WLAN anders. Ein Kindle, der sich nach
einem Werksreset nicht mehr registrieren lässt, verliert seine Bücher. Den Jailbreak selbst erklärt dieses Repo nicht.

## Was der Kindle braucht

- Jailbreak mit KUAL und dem Hotfix (seine Shell-Integration zeigt Skripte in `documents/` als Einträge in der Bibliothek)
- `fbink` unter `/mnt/us/libkh/bin/fbink`
- KOReader, nur für den Rückfall ohne WLAN (das Rezeptbuch)

## Was wohin kommt

| Pfad hier | Auf dem Kindle (per USB) |
|---|---|
| `kuechendash/` | `extensions/kuechendash/`: KUAL-Erweiterung. `dash.sh` an/aus, `rezeptbuch.sh` holt das EPUB |
| `kuechendash/einstellungen.sh` | dort vorher die Adresse deines Servers eintragen |
| `documents/Rezepte.sh` | `documents/`: Eintrag „Rezepte“ in der Bibliothek, öffnet `/kindle` im Browser |
| `test/` | nicht auf den Kindle: Test der Skripte unter busybox |

Vom Mac kopiert, liegen neben den Dateien oft `._*`-Dateien. Die auf dem Kindle löschen, sonst gibt es in
`documents/` einen zweiten, kaputten Eintrag. Ein Skript nie überschreiben, während es läuft: erst „Dashboard aus“.

## Betrieb

- **An/aus:** KUAL → Kuechen-Dashboard → Dashboard an / Dashboard aus. Kein Autostart: nach einem Neustart des
  Kindle einmal „an“ tippen.
- **Rhythmus:** tagsüber alle 30 min, nachts 22–6 Uhr gar nicht. Das entscheidet der Server (`/schlaf`,
  einstellbar über `INTERVALL`, `NACHT_VON`, `NACHT_BIS`).
- **Server oder WLAN weg:** Das letzte Bild bleibt stehen, die Uhrzeit im Bild zeigt sein Alter. Der Kindle versucht
  es nach 10 min erneut, nach 3 Fehlschlägen in Folge nur noch alle 3 h.
- **Logs:** auf dem Kindle `extensions/kuechendash/dash.log`, der Akkuverlauf auf dem Server in `daten/akku.csv`.
- **Rezepte lesen:** In der Bibliothek „Rezepte“ antippen. Das öffnet den Browser auf `/kindle`: Rezeptliste, ein
  Rezept auf einem Bildschirm, Portionen, „Fehlendes auf die Liste“ und „Gekocht“. Direkt nach dem Aufwecken wartet
  es bis 40 s auf das WLAN. Ohne WLAN oder Server öffnet es das zuletzt geholte Rezeptbuch in KOReader.
- **Rezeptbuch holen** (für den Rückfall ohne WLAN): KUAL → Kuechen-Dashboard → Rezeptbuch holen.

## Test ohne Kindle

Die Mac-Shell verhält sich anders als die des Kindle. Der Test läuft deshalb unter busybox in einem Wegwerf-Container:
einen Ordner mit `stubs/`, `szenario.sh` und, im Unterordner `ext/`, den Skripten `dash.sh`, `rezeptbuch.sh`,
`Rezepte.sh` und einer `einstellungen.sh` mit `SERVER=http://stub` füllen, dann

```bash
docker run --rm -v "$PWD/ordner:/t" busybox:1.37 sh /t/szenario.sh
```

## Was auf diesem Kindle gilt (gemessen im November 2026)

- Über den Schlafbildschirm gezeichnet bleibt ein Bild stehen, auch im Tiefschlaf. Kurz blitzt vorher der normale
  Sperrbildschirm auf.
- `rtcWakeup` weckt nur, wenn er bei **jedem** `readyToSuspend` neu gesetzt wird. Einmal gesetzt oder direkt in
  `rtc1/wakealarm` geschrieben weckt er nicht.
- Nach dem Wecken im Schlafbildschirm kommt das WLAN nicht von selbst. Kurz `wirelessEnable 0` und wieder `1` bringt
  es in 12–32 s zurück, manchmal dauert es länger. `dash.sh` wartet deshalb 60 s. Länger geht nicht: Nach dem Wecken
  bleiben etwa 110 s, bis der Wecker neu gesetzt sein muss.
- `deferSuspend` geht im Schlafbildschirm nicht.
- busybox-ash startet `cmd > fifo &` über einen Zwischenprozess: `$!` ist nicht `cmd`. `dash.sh` erkennt seinen
  Daemon am Namen in `/proc/*/cmdline`.
- Das busybox des Kindle ist älter als `busybox:1.37` im Test. `head -c` fehlt zum Beispiel, `dd bs=2 count=1` geht.
  Bei neuen Befehlen also nur Grundfunktionen nutzen.
- Der Browser ist ein WebKit von 2010: kein Flexbox, keine CSS-Variablen, kein neues JavaScript. Er unterstreicht
  jeden Link. Deshalb haben die Seiten unter `/kindle` ihr eigenes, schlichtes Aussehen und Knöpfe statt Links.
- Beim Beenden startet KOReader die Amazon-Dienste neu. Dabei stürzt gelegentlich der Update-Dienst ab und hinterlässt
  einen Bericht in `documents/` und eine große `.core`-Datei im Hauptordner. Ohne Folgen, aber wegräumen.
- Die Kindle-Uhr kann um eine Stunde danebenliegen. Das ist egal, weil der Server die Uhrzeit ins Bild malt.
