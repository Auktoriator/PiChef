"""Selbsttest fuer dash.py: .venv/bin/python test_dash.py (ohne Netz, ohne Server).

rezepte.py liegt im Nachbarordner rezepte/ (im Container im selben Ordner)."""
import io
import os
import sys
from datetime import datetime

os.environ.pop("LAT", None)  # kein Wetterabruf im Test
os.environ.update(INTERVALL="1800", NACHT_VON="22", NACHT_BIS="6", NAMEN="raspberrypi, LOCALHOST,.zuhause.example,.")
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rezepte"))
import dash  # noqa: E402
from PIL import Image  # noqa: E402


def t(h, m=0, s=0):
    return datetime(2026, 11, 3, h, m, s).astimezone()


assert dash.schlaf_sekunden(t(12)) == 1800
assert dash.schlaf_sekunden(t(6)) == 1800
assert dash.schlaf_sekunden(t(21, 59)) == 1800
assert dash.schlaf_sekunden(t(22)) == 8 * 3600
assert dash.schlaf_sekunden(t(23)) == 7 * 3600
assert dash.schlaf_sekunden(t(3)) == 3 * 3600
assert dash.schlaf_sekunden(t(5, 59, 30)) == 60

bild = Image.open(io.BytesIO(dash.zeichnen("42", t(12))))
assert bild.size == (758, 1024) and bild.mode == "L", (bild.size, bild.mode)
assert {v for v, n in enumerate(bild.histogram()) if n} <= {v * 17 for v in range(16)}

# Balkon: Home Assistant schickt den Wert (POST /balkon); den Weg ueber HTTP prueft test_rezepte.py
assert dash.balkon() is None  # noch nichts geschickt: Open-Meteo gilt
dash.balkon_merken("4.8")
assert dash.balkon() == 4.8
for unsinn in ["unavailable", "", "nan", "inf", "61", "-51"]:
    try:
        dash.balkon_merken(unsinn)
        raise AssertionError(unsinn)
    except ValueError:
        pass
assert dash.balkon() == 4.8  # Unsinn ueberschreibt nichts
dash._balkon["zeit"] -= dash.BALKON_FRIST + 1
assert dash.balkon() is None  # zu alt: Open-Meteo gilt
assert dash.zeichnen("42", t(12))  # ohne Netz und ohne Balkonwert gibt es trotzdem ein Bild

# Altes Wetter verfaellt: Nach einer Nacht ohne Netz stuende sonst unter „Heute“ die Vorhersage von gestern
dash.LAT, dash.LON = "48.1", "11.6"
jetzt = dash.time.time()
dash._wetter.update(zeit=jetzt, daten={"alt": 1}, ok=jetzt)  # zeit=jetzt: kein Abruf im Test
assert dash.wetter() == {"alt": 1}
dash._wetter["ok"] = jetzt - dash.WETTER_FRIST - 1
assert dash.wetter() is None
dash.LAT = dash.LON = None

# Einkauf als Aufzaehlung, abgeschnitten mit „und N weitere“
from PIL import ImageDraw  # noqa: E402
d = ImageDraw.Draw(Image.new("L", (dash.W, dash.H), 255))
liste = [{"name": f"Artikel {i}"} for i in range(20)]
dash.vorrat.einkaufsliste = lambda: liste[:n]
for n, y, erwartet in [(0, 400, []), (3, 400, ["Artikel 0", "Artikel 1", "Artikel 2"]),
                       (20, 400, ["Artikel 0", "Artikel 1", "Artikel 2", "Artikel 3", "Artikel 4", "und 15 weitere"]),
                       (20, 640, [])]:
    assert dash.einkaufen(d, 630, y, 354) == erwartet, (n, y)
n = 6  # genau so viele, wie passen: kein „weitere“
assert dash.einkaufen(d, 630, 400, 354)[-1] == "Artikel 5"
# Host-Pruefung gegen DNS-Rebinding: eigene Namen und IPs ja, fremde Namen nein
# Namen kommen aus NAMEN (oben gesetzt); ein Eintrag mit Punkt vorn ist eine ganze Zone, ein Punkt allein zaehlt nicht
for gut in [None, "10.0.0.5:8094", "127.0.0.1:8094", "raspberrypi", "localhost:8094", "[::1]:8094",
            "k-abc123.zuhause.example", "K-ABC123.ZUHAUSE.EXAMPLE."]:
    assert dash.host_erlaubt(gut), gut
for schlecht in ["boese.example", "zuhause.example.boese.example", "xzuhause.example", "zuhause.example",
                 "k.zuhause.example.example:8094", "raspberrypi.local", "x."]:
    assert not dash.host_erlaubt(schlecht), schlecht

print("ok")
