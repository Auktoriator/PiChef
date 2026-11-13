#!/usr/bin/env python3
"""Kuechen-Dashboard: rendert ein Graustufen-PNG fuer den Kindle PW1 und sagt ihm, wann er wiederkommen soll.

GET /kueche.png?akku=NN&anlass=TEXT  -> 758x1024 PNG (im Querformat gezeichnet, fuers Panel gedreht)
GET /schlaf                          -> Sekunden bis zum naechsten Wecken
POST /balkon  wert=4.8               -> Home Assistant schickt die Balkontemperatur (rest_command, nur LAN)
alles andere                         -> Rezept-Seite (rezepte.py)
python3 dash.py --bild datei.png     -> nur ein Vorschaubild schreiben, ohne Server

Einstellungen ueber Umgebungsvariablen: ORT, LAT, LON, PORT, DREHUNG, INTERVALL, NACHT_VON, NACHT_BIS, DATEN,
NAMEN (unter welchen Namen der Server erreichbar ist, siehe host_erlaubt).
"""
import csv
import functools
import io
import ipaddress
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from PIL import Image, ImageDraw, ImageFont

import rezepte
import vorrat

ORT = os.environ.get("ORT", "")
LAT = os.environ.get("LAT")
LON = os.environ.get("LON")
PORT = int(os.environ.get("PORT", "8080"))
DREHUNG = int(os.environ.get("DREHUNG", "90"))  # 90 oder 270, je nachdem wie der Kindle haengt; 0 = Vorschau
INTERVALL = int(os.environ.get("INTERVALL", "1800"))
NACHT_VON = int(os.environ.get("NACHT_VON", "22"))
NACHT_BIS = int(os.environ.get("NACHT_BIS", "6"))
assert NACHT_BIS < NACHT_VON, "Nacht muss ueber Mitternacht gehen, z. B. 22 bis 6"

W, H = 1024, 758
TAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]
WETTERTEXT = {
    0: "Klar", 1: "Überwiegend klar", 2: "Teils bewölkt", 3: "Bedeckt", 45: "Nebel", 48: "Reifnebel",
    51: "Leichter Niesel", 53: "Niesel", 55: "Starker Niesel", 56: "Gefr. Niesel", 57: "Gefr. Niesel",
    61: "Leichter Regen", 63: "Regen", 65: "Starker Regen", 66: "Gefr. Regen", 67: "Gefr. Regen",
    71: "Leichter Schnee", 73: "Schnee", 75: "Starker Schnee", 77: "Schneegriesel",
    80: "Leichte Schauer", 81: "Schauer", 82: "Heftige Schauer", 85: "Schneeschauer", 86: "Schneeschauer",
    95: "Gewitter", 96: "Gewitter, Hagel", 99: "Gewitter, Hagel",
}
SCHRIFTEN = {
    False: ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf"],
    True: ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"],
}
WETTER_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
              "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
              "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
              "&timezone=auto&forecast_days=3")
_wetter = {"zeit": 0.0, "daten": None, "ok": 0.0}
WETTER_FRIST = 3 * 3600  # aelter: lieber „Kein Wetter“ als unter „Heute“ die Vorhersage von gestern
# Home Assistant schickt bei jeder Aenderung und alle 10 min. Seit 2026-11-06 schickt HA, statt dass das Dashboard
# mit Token fragt: Ein HA-Token darf auch Geraete schalten und gehoert nicht in einen Dienst, der spaeter von aussen
# erreichbar ist. Zwei verpasste Meldungen: dann gilt Open-Meteo.
_balkon = {"wert": None, "zeit": 0.0}
BALKON_FRIST = 1800
# Der Kindle setzt den Wecker erst kurz vor dem Einschlafen: Gemessen in akku.csv (04./05.11.2026) kommt er
# ~110 s nach dem genannten Termin. Nur fuer die Anzeige „nächstes Bild ca.“.
VERZUG = 110
AKKU = {str(n) for n in range(101)}  # alles andere wird „?“


@functools.cache
def schrift(groesse, fett=False):
    for pfad in SCHRIFTEN[fett]:
        if os.path.exists(pfad):
            return ImageFont.truetype(pfad, groesse)
    return ImageFont.load_default(groesse)


def wetter():
    """Open-Meteo, hoechstens alle 10 Minuten abgerufen; bei Fehlern bleibt der letzte Stand bis WETTER_FRIST."""
    if not (LAT and LON):
        return None
    if time.time() - _wetter["zeit"] > 600:
        _wetter["zeit"] = time.time()
        try:
            with urllib.request.urlopen(WETTER_URL.format(lat=LAT, lon=LON), timeout=10) as r:
                _wetter.update(daten=json.load(r), ok=time.time())
        except Exception as e:  # ohne Wetter trotzdem ein Bild liefern
            print("Wetter-Fehler:", e, flush=True)
    if time.time() - _wetter["ok"] > WETTER_FRIST:
        return None
    return _wetter["daten"]


def balkon():
    """Zuletzt von Home Assistant geschickte Balkontemperatur oder None, dann gilt die von Open-Meteo."""
    if time.time() - _balkon["zeit"] > BALKON_FRIST:
        return None
    return _balkon["wert"]


def balkon_merken(text):
    """Wert aus POST /balkon; ValueError bei allem, was keine plausible Temperatur ist (auch nan, inf)."""
    wert = float(text)
    if not -50 <= wert <= 60:
        raise ValueError(text)
    _balkon.update(wert=wert, zeit=time.time())


def schlaf_sekunden(jetzt):
    """Tagsueber INTERVALL, nachts bis NACHT_BIS Uhr."""
    if NACHT_BIS <= jetzt.hour < NACHT_VON:
        return INTERVALL
    morgen = jetzt.replace(hour=NACHT_BIS, minute=0, second=0, microsecond=0)
    if morgen <= jetzt:
        morgen += timedelta(days=1)
    # shortcut: in der Nacht der Zeitumstellung liegt das Wecken eine Stunde daneben; reicht fuer die Kueche
    return max(60, int((morgen - jetzt).total_seconds()))


def kuerzen(d, text, font, breite):
    while text and d.textlength(text, font=font) > breite:
        text = text[:-2] + "…"
    return text


def umbrechen(d, text, font, breite):
    zeilen = [""]
    for wort in text.split():
        probe = f"{zeilen[-1]} {wort}".strip()
        if d.textlength(probe, font=font) <= breite or not zeilen[-1]:
            zeilen[-1] = probe
        else:
            zeilen.append(wort)
    return zeilen


def einkaufen(d, x, y, breite, unten=650):
    """Kachel „Einkauf“: Anzahl in der Kopfzeile, darunter die Artikel, so viele bis `unten` passen (Wunsch 2026-11-06).
    Gibt die gezeichneten Zeilen zurueck (fuer den Test)."""
    try:
        artikel = [a["name"] for a in vorrat.einkaufsliste()]
        n = len(artikel)
        text = "nichts" if n == 0 else "1 Sache" if n == 1 else f"{n} Sachen"
    except Exception as f:  # kaputte vorrat.json: Bild trotzdem liefern
        print("Einkauf-Fehler:", repr(f), flush=True)
        artikel, text = [], "nicht lesbar"
    d.text((x, y), "Einkauf", font=schrift(34, True), fill=0)
    d.text((x + breite, y + 6), text, font=schrift(30), fill=0, anchor="ra")
    platz = max(0, (unten - y - 52) // 34 + 1)
    if len(artikel) > platz:
        artikel = artikel[:platz - 1] + [f"und {len(artikel) - platz + 1} weitere"] if platz else []
    for i, name in enumerate(artikel):
        d.text((x, y + 52 + i * 34), "•", font=schrift(26), fill=0)
        d.text((x + 22, y + 52 + i * 34), kuerzen(d, name, schrift(26), breite - 22), font=schrift(26), fill=0)
    return artikel


def zeichnen(akku, jetzt):
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)

    d.text((40, 28), f"{TAGE[jetzt.weekday()]}, {jetzt.day}. {MONATE[jetzt.month - 1]}", font=schrift(42, True), fill=0)
    d.text((W - 40, 36), ORT, font=schrift(32), fill=70, anchor="ra")
    d.line((40, 96, W - 40, 96), fill=0, width=3)

    w = wetter()
    if w:
        c, t = w["current"], w["daily"]
        b = balkon()
        temp = f"{round(c['temperature_2m'] if b is None else b)}°"
        d.text((36, 110), temp, font=schrift(160, True), fill=0)
        if b is not None:  # sonst ist die grosse Zahl die von Open-Meteo
            d.text((36 + d.textlength(temp, font=schrift(160, True)) + 16, 150), "Balkon", font=schrift(28), fill=70)
        d.text((40, 300), WETTERTEXT.get(c["weather_code"], "?"), font=schrift(42), fill=0)
        d.text((40, 355), f"gefühlt {round(c['apparent_temperature'])}°   Wind {round(c['wind_speed_10m'])} km/h",
                font=schrift(28), fill=70)
        for i, name in enumerate(["Heute", "Morgen", TAGE[(jetzt.weekday() + 2) % 7]]):
            x, y = 40 + i * 186, 430
            d.text((x, y), name, font=schrift(26, True), fill=0)  # 26: "Donnerstag" passt auch in DejaVu in die Spalte
            d.text((x, y + 44), f"{round(t['temperature_2m_max'][i])}° / {round(t['temperature_2m_min'][i])}°",
                   font=schrift(34), fill=0)
            d.text((x, y + 92), f"Regen {t['precipitation_probability_max'][i]} %", font=schrift(26), fill=70)
            d.text((x, y + 130), kuerzen(d, WETTERTEXT.get(t["weather_code"][i], "?"), schrift(24), 176),
                   font=schrift(24), fill=0)
    else:
        grund = "Ort fehlt (LAT/LON)" if not (LAT and LON) else "Abruf fehlgeschlagen"
        d.text((40, 140), "Kein Wetter", font=schrift(48, True), fill=0)
        d.text((40, 210), grund, font=schrift(30), fill=70)

    d.line((600, 120, 600, 670), fill=0, width=2)
    x, breite = 630, W - 40 - 630
    d.text((x, 120), "Heute kochen", font=schrift(34, True), fill=0)
    r = rezepte.heute()
    y = 172
    if r:
        zeilen = umbrechen(d, r["titel"], schrift(30, True), breite)
        for i, zeile in enumerate(zeilen[:3]):  # bis drei Zeilen Titel, erst dann gekuerzt
            text = " ".join(zeilen[i:]) if i == 2 else zeile
            d.text((x, y), kuerzen(d, text, schrift(30, True), breite), font=schrift(30, True), fill=0)
            y += 38
        meta = "   ".join(t for t in (r["zeit"], r["portionen"] and f"{r['portionen']} Portionen") if t)
        for t in (meta, rezepte.kurz(r)):  # Dauer und Naehrwerte statt der Zutaten
            if t:
                d.text((x, y + 6), kuerzen(d, t, schrift(26), breite), font=schrift(26), fill=0)
                y += 36
    else:
        d.multiline_text((x, y), "Nichts geplant.\nAuf der Rezept-Seite\n„Heute kochen“ tippen.",
                         font=schrift(28), fill=70, spacing=10)
        y += 3 * 38
    einkaufen(d, x, y + 40, breite)

    d.line((40, 688, W - 40, 688), fill=0, width=2)
    naechstes = jetzt + timedelta(seconds=schlaf_sekunden(jetzt) + VERZUG)
    d.text((40, 704), f"Stand {jetzt:%H:%M}   Akku {akku} %   nächstes Bild ca. {naechstes:%H:%M}",
           font=schrift(26), fill=70)

    img = img.point(lambda v: v // 17 * 17)  # 16 Graustufen wie das Panel
    if DREHUNG:
        img = img.rotate(DREHUNG, expand=True)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def akku_merken(jetzt, anlass, akku):
    os.makedirs(rezepte.DATEN, exist_ok=True)
    with open(os.path.join(rezepte.DATEN, "akku.csv"), "a", newline="") as f:
        csv.writer(f).writerow([jetzt.isoformat(timespec="seconds"), anlass, akku])


# DNS-Rebinding (gefunden 2026-11-04): Eine fremde Webseite laesst ihren
# Namen auf diesen Rechner umschwenken und ist danach "dieselbe Seite" -
# Host und Origin stimmen ueberein, die Origin-Pruefung in do_POST greift
# nicht. Dafuer braucht sie aber ihren eigenen Domainnamen im Host-Kopf.
# Deshalb gilt nur eine IP-Adresse oder ein Name aus NAMEN (mit Komma). Ein Eintrag mit Punkt vorn ist eine ganze
# Zone („.zuhause.example“ erlaubt jeden Namen darunter): nur fuer Zonen, in denen niemand sonst Namen anlegen kann.
NAMEN = {n.strip().lower() for n in os.environ.get("NAMEN", "raspberrypi,raspberrypi.local,localhost").split(",")}
EIGENE_NAMEN = {n for n in NAMEN if n and not n.startswith(".")}
ZONEN = tuple(n for n in NAMEN if n.startswith(".") and len(n) > 1)


def host_erlaubt(host):
    """Fehlt der Kopf (alte HTTP/1.0-Clients), bleibt es erlaubt: Browser schicken ihn immer."""
    if not host:
        return True
    name = host.strip().lower()
    if name.startswith("["):            # [IPv6]:Port
        name = name[1:].split("]")[0]
    elif name.count(":") == 1:          # Name:Port oder IPv4:Port
        name = name.split(":")[0]
    if name.rstrip(".") in EIGENE_NAMEN or name.rstrip(".").endswith(ZONEN):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    # Ohne Frist haelt eine langsame Verbindung ihren Thread beliebig lange.
    timeout = 15

    def fremder_host(self):
        if host_erlaubt(self.headers.get("Host")):
            return False
        self.send_error(403)
        return True

    def do_GET(self):
        if self.fremder_host():
            return
        url = urlparse(self.path)
        q = parse_qs(url.query)
        jetzt = datetime.now().astimezone()
        try:
            if url.path == "/kueche.png":
                akku = q.get("akku", ["?"])[0]
                akku = akku if akku in AKKU else "?"
                akku_merken(jetzt, q.get("anlass", ["?"])[0][:20], akku)
                self.antwort("image/png", zeichnen(akku, jetzt))
            elif url.path == "/schlaf":
                self.antwort("text/plain", str(schlaf_sekunden(jetzt)).encode())
            else:
                self.antwort(*rezepte.get(url.path, q))
        except FileNotFoundError:
            self.send_error(404)
        except Exception as e:  # Kindle behaelt dann einfach sein letztes Bild
            print("Fehler:", repr(e), flush=True)
            self.send_error(500)

    def do_POST(self):
        if self.fremder_host():
            return
        url = urlparse(self.path)
        host = self.headers.get("Host", "")
        eigen = f"http://{host}"
        try:
            # Fremde Webseiten im Browser duerfen hier nichts abschicken. https: von unterwegs, nginx reicht den Host durch.
            if self.headers.get("Origin", eigen) not in (eigen, f"https://{host}"):
                return self.send_error(403)
            try:
                laenge = int(self.headers.get("Content-Length", 0))
                # Die Untergrenze zaehlt: Bei -1 liest rfile.read() bis zum
                # Verbindungsende, also beliebig viel in den Speicher (2026-11-04).
                if not 0 <= laenge <= 200_000:
                    return self.send_error(413)
                form = parse_qs(self.rfile.read(laenge).decode())
            except ValueError:  # Laenge keine Zahl oder Inhalt kein UTF-8
                return self.send_error(400)
            if url.path == "/balkon":
                try:
                    balkon_merken(form.get("wert", [""])[0])
                except ValueError:
                    return self.send_error(400)
                return self.antwort("text/plain", b"ok")
            self.antwort(*rezepte.post(url.path, form))
        except FileNotFoundError:
            self.send_error(404)
        except Exception as e:
            print("Fehler:", repr(e), flush=True)
            self.send_error(500)

    def antwort(self, typ, daten, code=200, ziel=None):
        self.send_response(code)
        self.send_header("Content-Type", typ)
        if ziel:
            self.send_header("Location", ziel)
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--bild"]:
        with open(sys.argv[2], "wb") as f:
            f.write(zeichnen("99", datetime.now().astimezone()))
    else:
        print(f"Kuechen-Dashboard auf Port {PORT}", flush=True)
        ThreadingHTTPServer(("", PORT), Handler).serve_forever()
