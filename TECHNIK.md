# Technik

Für alle, die hineinsehen oder etwas ändern wollen. Bedienung und Start: [README.md](README.md).

## Aufbau

| Pfad | Inhalt |
|---|---|
| `dashboard/dash.py` | Der Server (Pythons `http.server`). Zeichnet das Bild für den Kindle und reicht alle anderen Adressen an `rezepte.py` weiter |
| `rezepte/rezepte.py` | Rezepte: Liste mit Filtern, ein Rezept, Portionen umrechnen, Kochmodus, Prompt, Vorschau, Seiten für den Kindle-Browser |
| `rezepte/vorrat.py` | Vorrat, Einkaufsliste, Zuordnen von Zutaten zu Artikeln, „Kochen“, Startseite |
| `rezepte/prompt.txt` | Der Prompt und damit das Rezeptformat |
| `rezepte/stil.css` | Das Aussehen der Handy-Seiten. Keine fremden Schriften, keine fremden Server |
| `rezepte/katalog-start.txt` | Der Startkatalog. Daraus entsteht beim ersten Ändern `daten/vorrat.json` |
| `demo/` | Beispieldaten zum Ansehen |
| `kindle/` | Skripte für den Kindle, siehe [kindle/README.md](kindle/README.md) |
| `Dockerfile`, `compose.yaml` | Der Container. Er kopiert die Dateien flach nach `/app`. Neue Dateien im `Dockerfile` eintragen |

Die Seiten sind fertiges HTML vom Server. Ohne JavaScript geht fast alles, mit geht es ohne Neuladen.

## Einstellungen

Umgebungsvariablen in `compose.yaml`:

| Name | Bedeutung |
|---|---|
| `PORT` | Port des Servers |
| `DATEN` | Ordner für Rezepte, Vorrat und Einkaufsliste |
| `NAMEN` | Namen, unter denen die Seite aufgerufen werden darf, mit Komma. IP-Adressen gehen immer. Ein Eintrag mit Punkt vorn erlaubt eine ganze eigene Zone |
| `ORT`, `LAT`, `LON` | Ort und Koordinaten für das Wetter im Kindle-Bild. Ohne `LAT` und `LON` fragt der Server kein Wetter ab |
| `INTERVALL`, `NACHT_VON`, `NACHT_BIS` | Wie oft der Kindle sein Bild holt (Sekunden) und wann er nachts ruht |
| `DREHUNG` | 90 oder 270, je nachdem, wie der Kindle hängt |

## Daten

- `daten/rezepte/<name>.md`: ein Rezept je Datei, im Format aus `prompt.txt`. Gelöschte Rezepte liegen in
  `daten/rezepte/papierkorb/`.
- `daten/vorrat.json`: alle Artikel mit Stand, die Einkaufsliste und die Zuordnungen. Ist die Datei kaputt, zeigt
  die Seite einen Fehler und überschreibt sie nicht.
- `daten/heute.txt`, `daten/vorlieben.txt`: „Heute kochen“ und die Vorlieben für den Prompt.
- `daten/akku.csv`: Akkustand des Kindle bei jedem Abruf.

## Adressen für andere Geräte

| Adresse | Für |
|---|---|
| `GET /einkauf.json` | Home Assistant und andere: `{"anzahl": 3, "artikel": [{"name", "bereich", "grund"}]}` |
| `POST /balkon` mit `wert=4.8` | Ein Thermometer schickt die Außentemperatur für das Kindle-Bild. Nach 30 min ohne neuen Wert gilt wieder Open-Meteo |
| `GET /kueche.png?akku=NN`, `GET /schlaf` | Der Kindle holt sein Bild und fragt, wann er wiederkommen soll |
| `GET /kindle` | Rezepte für den Browser des Kindle |

Beispiel für Home Assistant:

```yaml
rest:
  - resource: http://127.0.0.1:8094/einkauf.json
    scan_interval: 300
    sensor:
      - name: Einkaufsliste
        value_template: "{{ value_json.anzahl }}"
        json_attributes: [artikel]
```

## Sicherheit

Die App hat keinen Login und ist für ein Heimnetz gedacht. Was sie trotzdem tut:

- Sie antwortet nur unter einer IP-Adresse oder einem Namen aus `NAMEN`. Das schützt vor DNS-Rebinding, bei dem eine
  fremde Webseite ihren Namen auf deinen Pi zeigen lässt.
- Ein `POST` mit fremdem `Origin` wird abgelehnt. Eine fremde Webseite im Handy-Browser kann so nichts löschen.
  Ohne `Origin` geht er durch (Home Assistant, alter Kindle-Browser).
- Rezeptnamen bestehen nur aus `a-z`, `0-9` und `-`, alle Inhalte werden für HTML maskiert, die Größe einer Anfrage
  ist begrenzt.
- Der Container läuft ohne Root, ohne Capabilities und mit schreibgeschütztem Dateisystem.

Was sie nicht tut: Der Port aus `compose.yaml` ist an allen Adressen des Rechners offen, und Docker öffnet ihn an
einer Firewall wie ufw vorbei. Hat dein Pi eine öffentliche IPv6-Adresse, schützt ihn nur die Firewall des Routers.

Eine Sicherheitslücke bitte nicht als öffentliches Issue melden, sondern über „Report a vulnerability“ im Reiter
„Security“ des Repos.

## Tests

Beide laufen ohne Netz und ohne Docker, mit Python 3.13 oder neuer und Pillow:

```bash
python3 dashboard/test_dash.py
python3 rezepte/test_rezepte.py
```

Der Container nutzt Python 3.13. Wer am eigenen Rechner ein neueres Python hat, nutzt nur, was 3.13 kann.

## Bekannte Grenzen

- Der Vorrat kennt keine Mengen. „Wenig“ zählt für Rezepte als da.
- Beim Umrechnen der Portionen bleiben Mengen im Text der Schritte, wie sie sind. Die Seite sagt das dazu.
- Nährwerte schätzt die KI, die das Rezept schreibt.
- Im Kochmodus bleibt das Display nur über `https` an (eine Vorgabe der Browser). Im Heimnetz über `http` zeigt
  die Seite einen Hinweis.
