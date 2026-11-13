"""Selbsttest fuer rezepte.py samt Webseite und Kachel „Heute kochen“: .venv/bin/python test_rezepte.py (ohne Netz).

Der Server (dash.py) liegt im Nachbarordner dashboard/ (im Container im selben Ordner)."""
import io
import os
import re
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from urllib.parse import urlencode

os.environ.pop("LAT", None)  # kein Wetterabruf im Test
os.environ["DATEN"] = tempfile.mkdtemp()
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dashboard"))
import dash  # noqa: E402
import rezepte  # noqa: E402
from PIL import Image  # noqa: E402

# So kopiert man eine Antwort aus dem Chat: mit Codeblock-Zaun und Satz davor
ANTWORT = """Hier ist dein Rezept:
```markdown
# Zucchini-Pasta mit Zitrone
Mahlzeit: Abendessen
Portionen: 2
Zeit: 20 min
Nährwerte pro Portion: 530 kcal, 19 g Eiweiß, 16,5 g Fett, 76 g Kohlenhydrate
Tags: vegetarisch, schnell

## Zutaten
- 200 g Spaghetti
- 1 Stück Zucchini
- 1 Stück Bio-Zitrone <scharf> & frisch

## Zubereitung
1. Spaghetti in Salzwasser 9 min kochen.
2. Zucchini raspeln und in 1 EL Öl 3 min braten.

## Tipp
Mit Parmesan bestreuen.
```
"""

text = rezepte.saeubern(ANTWORT)
assert text.startswith("# Zucchini") and "```" not in text and "Hier ist" not in text, text
r, fehler, hinweise = rezepte.lesen(text)
assert not fehler and not hinweise, (fehler, hinweise)
assert r["tags"] == ["vegetarisch", "schnell"] and r["portionen"] == "2" and r["tipp"] == "Mit Parmesan bestreuen."
assert r["mahlzeit"] == ["abend"] and r["naehrwerte"] == {"kcal": "530", "eiweiss": "19", "fett": "16,5", "kh": "76"}
assert rezepte.kurz(r) == "530 kcal, E 19 g, F 16,5 g", rezepte.kurz(r)
assert rezepte.lesen("# A\nMahlzeit: beides\n")[0]["mahlzeit"] == ["mittag", "abend"]
assert rezepte.lesen("# A\nMahlzeit: Mittagessen, Abendessen\n")[0]["mahlzeit"] == ["mittag", "abend"]
assert rezepte.lesen("# A\nNährwerte: ca. 600 kcal, 30 g Protein\n")[0]["naehrwerte"] == {"kcal": "600", "eiweiss": "30"}
import time  # noqa: E402
beginn = time.time()
rezepte.lesen("# A\nNährwerte: " + "1" * 200_000 + "\n")  # so lang darf ein POST sein; ungebremst ~1 h CPU
assert time.time() - beginn < 1, time.time() - beginn
ALT = "\n".join(z for z in text.splitlines() if not z.startswith(("Mahlzeit", "Nährwerte")))  # Rezepte von vor 2026-11-05
r_alt, f_alt, h_alt = rezepte.lesen(ALT)
assert not f_alt and len(h_alt) == 2 and rezepte.kurz(r_alt) == "" and r_alt["mahlzeit"] == [], h_alt
assert r["zutaten"][0] == "200 g Spaghetti" and r["zubereitung"][1].startswith("Zucchini raspeln"), r
assert len(rezepte.lesen("# Nur ein Titel\n")[1]) == 2
assert rezepte.name_aus("Käse-Spätzle für Groß & Klein") == "kaese-spaetzle-fuer-gross-klein"
# Mehrere Rezepte in einer Antwort: nur der Inhalt der Codebloecke zaehlt, getrennt wird an jeder Zeile „# Titel“
R2 = text.replace("Zucchini-Pasta mit Zitrone", "Zweites")
R3 = "# Drittes\n## Zutaten\n- 1 Ei\n"  # Zubereitung fehlt
EIN_BLOCK = f"Gern!\n```markdown\n{text}\n{R2}```\nGuten Appetit!"
DREI_BLOECKE = f"```\n{text}```\nUnd noch eins:\n```\n{R2}```\nUnd:\n```\n{R3}```\nViel Spaß"
assert rezepte.teilen(EIN_BLOCK) == [text, R2] and rezepte.teilen(DREI_BLOECKE) == [text, R2, R3]
assert rezepte.teilen(text + R2) == [text, R2] and rezepte.teilen("```\n" + text + R2) == [text, R2]  # ohne Zaeune, Zaun nicht zu
assert rezepte.teilen(ANTWORT) == [text] and rezepte.teilen("nur Geplauder") == ["nur Geplauder\n"]
assert len(rezepte.teilen(text * 20)) == 10
beginn = time.time()
for lang in ["```\n" * 50_000, "```x\n" + "a\n" * 100_000, "# \n" * 50_000]:  # so lang darf ein POST sein
    rezepte.teilen(lang)
assert time.time() - beginn < 2, time.time() - beginn

# Portionen umrechnen: (Zeile, Faktor, Ergebnis); g/ml auf 1/5/10, ab 1000 kg/l; Stueck & Co. auf ½; Eier ganz
for zeile_, faktor, soll in [
    ("200 g Spaghetti", 2, "400 g Spaghetti"),
    ("200 g Spaghetti", 0.5, "100 g Spaghetti"),
    ("125 g Mozzarella", 1.5, "190 g Mozzarella"),
    ("15 g Parmesan", 0.5, "8 g Parmesan"),
    ("35 g Feta", 1.5, "55 g Feta"),
    ("600 g Kartoffeln", 2, "1,2 kg Kartoffeln"),
    ("1 kg Kartoffeln", 0.5, "500 g Kartoffeln"),
    ("150 ml Kokosmilch", 0.5, "75 ml Kokosmilch"),
    ("1 g Safran", 0.25, "0,3 g Safran"),  # unter 1 auf Zehntel, nie „0 g“
    ("2 ml Aroma", 1 / 6, "0,3 ml Aroma"),
    ("0,1 g Safran", 0.25, "0,1 g Safran"),
    ("600 ml Brühe", 2, "1,2 l Brühe"),
    ("1 Stück Zucchini", 1.5, "1 ½ Stück Zucchini"),
    ("0,5 Bund Petersilie", 0.5, "½ Bund Petersilie"),
    ("1,5 EL Olivenöl", 2, "3 EL Olivenöl"),
    ("1 TL Oregano, getrocknet", 0.5, "½ TL Oregano, getrocknet"),
    ("1/2 TL Zimt", 2, "1 TL Zimt"),
    ("½ Zitrone", 3, "1 ½ Zitrone"),
    ("1 ½ Stück Paprika", 2, "3 Stück Paprika"),
    ("2 Zwiebeln", 1.5, "3 Zwiebeln"),
    ("6–8 Stück Cherrytomaten", 0.5, "3–4 Stück Cherrytomaten"),
    ("1 Stück Ei", 0.5, "1 Stück Ei"),
    ("3 Stück Eier", 1.5, "5 Stück Eier"),
    ("1 Stück Eisbergsalat", 0.5, "½ Stück Eisbergsalat"),
    ("1 Prise Salz", 2, "1 Prise Salz"),
    ("Salz, Pfeffer", 2, "Salz, Pfeffer"),
    ("0,5 Stück Gurke", 1, "0,5 Stück Gurke"),
]:
    assert rezepte.skalieren(zeile_, faktor) == soll, (zeile_, faktor, rezepte.skalieren(zeile_, faktor), soll)
for kaputt in ["1/0 TL Zimt", "9" * 400 + " g Mehl"]:  # nicht rechenbar: die Zeile bleibt, statt Fehler 500
    assert rezepte.skalieren(kaputt, 2) == kaputt, kaputt
vier = rezepte.umgerechnet(r, "4")
assert vier["zutaten"][0] == "400 g Spaghetti" and vier["portionen"] == "4" and vier["basis"] == 2, vier
assert vier["zubereitung"] == r["zubereitung"] and r["zutaten"][0] == "200 g Spaghetti" and "basis" not in r
for n in ["2", "", "0", "13", "abc", "-1", "4.5", "²", "9" * 5000]:  # gleich, leer, ausserhalb 1..12 oder keine Zahl: unveraendert
    assert rezepte.umgerechnet(r, n) == r, n
for basis in ["2–3", "²", "9" * 5000]:  # Basis keine einfache Zahl
    assert rezepte.umgerechnet(dict(r, portionen=basis), "4")["zutaten"] == r["zutaten"], basis[:9]

srv = dash.ThreadingHTTPServer(("127.0.0.1", 0), dash.Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASIS = f"http://127.0.0.1:{srv.server_port}"


def hole(weg, origin=BASIS, **felder):
    """GET ohne Felder, sonst POST wie ein Formular; folgt Weiterleitungen."""
    req = urllib.request.Request(BASIS + weg, urlencode(felder, doseq=True).encode() if felder else None,
                                 {"Origin": origin} if origin else {})  # origin=None: wie HA, ohne Kopf
    with urllib.request.urlopen(req) as a:
        return a.geturl(), a.read()


def status(weg, **kw):
    try:
        hole(weg, **kw)
    except urllib.error.HTTPError as f:
        return f.code
    return 200


NAME = "zucchini-pasta-mit-zitrone"
assert hole("/speichern", text=ANTWORT)[0] == f"{BASIS}/rezept?d={NAME}"
assert hole("/speichern", text=ANTWORT)[0].endswith(f"{NAME}-2")  # gleicher Titel ueberschreibt nichts
assert b"Zutaten fehlen" in hole("/speichern", text="# Kaputt")[1] and len(rezepte.alle()) == 2
assert hole("/speichern", d=NAME, text=text.replace("Portionen: 2", "Portionen: 4"))[0].endswith(NAME)
assert rezepte.lesen(rezepte.text(NAME))[0]["portionen"] == "4"  # Bearbeiten ueberschreibt das eigene Rezept

seite = hole("/rezepte")[1].decode()
assert "Zucchini-Pasta" in seite and "vegetarisch" in seite and ">530</span> kcal" in seite and "E 19 g, F 16,5 g" in seite
assert "Zucchini-Pasta" in hole("/rezepte?m=abend")[1].decode() and "Zucchini-Pasta" not in hole("/rezepte?m=mittag")[1].decode()
assert "Zucchini-Pasta" in hole("/rezepte?m=quatsch")[1].decode()  # unbekannter Filter zeigt alle
# Filter: alle Tags muessen passen (Gross/klein egal), Chips schalten sich ab, Reiter behalten die Filter, Suchtext je Zeile
gefiltert = hole("/rezepte?t=Vegetarisch&t=schnell")[1].decode()
assert "Zucchini-Pasta" in gefiltert and '<a href="/rezepte?t=schnell" aria-current="true">vegetarisch</a>' in gefiltert
assert '<a href="/rezepte?m=abend&amp;t=vegetarisch&amp;t=schnell">Abendessen</a>' in gefiltert
assert 'data-suche="zucchini-pasta mit zitrone vegetarisch schnell 200 g spaghetti' in gefiltert and 'id="suche"' in gefiltert
leer = hole("/rezepte?t=vegetarisch&t=%3Cscript%3E")[1].decode()
assert "Kein Rezept passt" in leer and ">&lt;script&gt;</a>" in leer and leer.count("<script>") == 1
assert len(hole("/rezepte?" + "&".join(f"t=x{i}" for i in range(50)))[1].decode().split('aria-current="true"')) == 6  # hoechstens 5
assert ">Kohlenhydrate</th>" in hole(f"/rezept?d={NAME}")[1].decode()
assert "&lt;scharf&gt; &amp; frisch" in hole(f"/rezept?d={NAME}")[1].decode()  # Inhalt wird maskiert
# Portionen in der Adresse (die Datei hat jetzt 4): umgerechnet mit Hinweisen, Unsinn zeigt die Datei
acht = hole(f"/rezept?d={NAME}&portionen=8")[1].decode()
assert "400 g Spaghetti" in acht and "Umgerechnet von 4 Portionen" in acht and "Mengen im Text gelten für 4" in acht, acht
assert "&amp;portionen=9#zutaten" in acht and 'name="portionen" value="8"' in acht
for unsinn in ["abc", "99", "0", "%C2%B2", "8%3Cb%3E"]:
    s = hole(f"/rezept?d={NAME}&portionen={unsinn}")[1].decode()
    assert "200 g Spaghetti" in s and "Umgerechnet" not in s and 'name="portionen"' not in s, unsinn
assert hole("/heute", d=NAME, an="1", portionen="8")[0].endswith(f"/rezept?d={NAME}&portionen=8")
assert hole("/heute", d=NAME, an="0", portionen="8<b>")[0].endswith(f"/rezept?d={NAME}")  # wieder aus, ohne Unsinn in der Adresse
# Kochmodus: Zeitangaben werden Timer-Knoepfe, alle Abschnitte da, nur einer sichtbar, ohne Leiste unten
for roh, sek in [("9–10 min", 540), ("10 Sekunden", 10), ("4–5 Minuten", 240), ("1 Std.", 3600), ("2 stunden", 7200), ("3-4 MIN", 180)]:
    assert rezepte.dauern(f"Warte {roh} lang") == f'Warte <button type="button" class="uhr" data-sek="{sek}">{roh}</button> lang', roh
assert rezepte.dauern("<b>1,5 Std. & 2 EL") == "&lt;b&gt;1,5 Std. &amp; 2 EL" and "<b>" not in rezepte.dauern("<b> 5 min")
km = hole(f"/kochmodus?d={NAME}&schritt=2")[1].decode()
assert km.count('<section class="kochschritt"') == 3 and km.count('" hidden><h2>') == 2 and '<nav class="unten"' not in km
assert '<section class="kochschritt" data-schritt="2">' in km and 'data-schritt="0" hidden>' in km
assert 'data-sek="540">9 min</button>' in km and 'data-sek="180">3 min</button>' in km
assert "Schritt 2 von 2" in km and "Mengen im Text gelten" not in km and 'href="/gekocht?d=' + NAME + '">Fertig' in km
assert 'href="/rezept?d=' + NAME + '">Zurück</a>' in km and "<h2>Dafür</h2>" in km and "Bereitstellen" in km
assert '<section class="kochschritt" data-schritt="2">' in hole(f"/kochmodus?d={NAME}&schritt=99")[1].decode()
for s in ["abc", "-1", "", "%C2%B2"]:
    assert '<section class="kochschritt" data-schritt="0">' in hole(f"/kochmodus?d={NAME}&schritt={s}")[1].decode(), s
km8 = hole(f"/kochmodus?d={NAME}&portionen=8&schritt=1")[1].decode()
assert "400 g Spaghetti" in km8 and "Mengen im Text gelten für 4 Portionen." in km8 and "&amp;portionen=8&amp;schritt=2" in km8
assert f'/rezept?d={NAME}&amp;portionen=8"' in km8, [x for x in km8.split("<") if "portionen" in x]
assert "portionen" not in hole(f"/kochmodus?d={NAME}&portionen=abc")[1].decode().split("<main")[1].split("<script>")[0]
assert status("/kochmodus?d=gibts-nicht") == 404 and status("/kochmodus") == 404
assert f'href="/kochmodus?d={NAME}">Kochmodus' in hole(f"/rezept?d={NAME}")[1].decode()
assert f'href="/kochmodus?d={NAME}&amp;portionen=8">Kochmodus' in acht
for weg in ["/neu", f"/bearbeiten?d={NAME}"]:
    assert status(weg) == 200, weg
for weg in ["/rezept?d=../heute", "/rezept?d=gibts-nicht", "/quatsch"]:
    assert status(weg) == 404, weg
assert status("/loeschen", origin="http://fremd.example", d=NAME) == 403
assert status("/heute", d="../../etc/passwd") == 404


def mit_laenge(n):
    """POST mit selbst gesetztem Content-Length, ohne Inhalt: Bei -1 laese der Server sonst bis zum Verbindungsende."""
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
    c.putrequest("POST", "/vorschau")
    c.putheader("Origin", BASIS)
    c.putheader("Content-Length", n)
    c.endheaders()
    return c.getresponse().status


assert mit_laenge("-1") == 413 and mit_laenge("200001") == 413 and mit_laenge("x") == 400
import http.client  # noqa: E402
c = http.client.HTTPConnection("127.0.0.1", srv.server_port, timeout=5)
c.request("POST", "/vorschau", body=b"text=\xff", headers={"Origin": BASIS})
assert c.getresponse().status == 400  # kein UTF-8: Fehler des Absenders, nicht 500
# Akku vom Kindle: Unsinn wird „?“, das Bild kommt trotzdem (² gilt in Python als Ziffer, int() kennt es nicht)
for unsinn in ["%C2%B2", "9" * 5000, "101", "x"]:
    assert status(f"/kueche.png?akku={unsinn}") == 200, unsinn[:9]

hole("/heute", d=NAME, an="1")
assert rezepte.heute()["titel"] == "Zucchini-Pasta mit Zitrone" and "Heute</span>" in hole("/rezepte")[1].decode()
# Der Knopf schickt den Zielzustand: doppelt getippt oder von einer alten Seite gesendet aendert nichts
hole("/heute", d=NAME, an="1")
assert rezepte.heute_name() == NAME and '<button class="zweit" name="an" value="0">Nicht mehr heute' in hole(f"/rezept?d={NAME}")[1].decode()
# Der Hinweis auf den Kindle steht nur, wenn einer in den letzten zwei Tagen sein Bild geholt hat (akku.csv, oben geschrieben)
akku = os.path.join(rezepte.DATEN, "akku.csv")
assert "Steht auf dem Kindle" in hole(f"/rezept?d={NAME}")[1].decode() and "Rezeptbuch" not in hole("/rezepte")[1].decode()
os.utime(akku, (time.time() - 3 * 86400,) * 2)
assert "Steht auf dem Kindle" not in hole(f"/rezept?d={NAME}")[1].decode()
os.rename(akku, akku + ".weg")
assert "Steht auf dem Kindle" not in hole(f"/rezept?d={NAME}")[1].decode()  # nie ein Kindle da gewesen
os.rename(akku + ".weg", akku)
hole("/heute", d=NAME + "-2", an="0")  # „Nicht mehr heute“ an einem anderen Rezept nimmt die Markierung nicht weg
assert rezepte.heute_name() == NAME and '<button name="an" value="1">Heute kochen' in hole(f"/rezept?d={NAME}-2")[1].decode()
bild = Image.open(io.BytesIO(dash.zeichnen("42", datetime.now().astimezone())))
assert bild.size == (758, 1024)
dash.DREHUNG = 0
Image.open(io.BytesIO(dash.zeichnen("42", datetime.now().astimezone()))).save(os.path.join(rezepte.DATEN, "kachel.png"))

hole("/speichern", text=ALT.replace("Zucchini-Pasta mit Zitrone", "Alt ohne Werte"))
epub = zipfile.ZipFile(io.BytesIO(hole("/rezeptbuch.epub")[1]))
erste = epub.infolist()[0]
assert erste.filename == "mimetype" and erste.compress_type == zipfile.ZIP_STORED
assert epub.read("mimetype") == b"application/epub+zip"
for datei in epub.namelist():
    if datei.endswith((".xhtml", ".opf", ".ncx", ".xml")):
        ET.fromstring(epub.read(datei))  # wohlgeformtes XML, sonst lehnt KOReader ab
assert len([d for d in epub.namelist() if d.startswith("OEBPS/r-")]) == 3
inhalt = epub.read("OEBPS/inhalt.xhtml").decode()
assert "<span>Abendessen</span>" in inhalt and "Mittagessen" not in inhalt, inhalt
assert "Zucchini-Pasta mit Zitrone (530 kcal, E 19 g, F 16,5 g)" in inhalt
assert "<span>Weitere</span><ol><li><a href=\"r-alt-ohne-werte.xhtml\">Alt ohne Werte</a>" in inhalt  # alter Stand ohne Klammer

hole("/loeschen", d=NAME)
assert rezepte.heute() is None and len(rezepte.alle()) == 2 and len(os.listdir(rezepte.PAPIERKORB)) == 1
hole("/heute", d=NAME + "-2", an="1")
hole("/heute", d=NAME + "-2", an="0")  # „Nicht mehr heute“ nimmt die Markierung wieder weg
assert rezepte.heute() is None

# --- Vorrat und Einkaufsliste (vorrat.py) ---
import vorrat  # noqa: E402

k = vorrat.start_lesen(open(vorrat.START, encoding="utf-8").read())
assert all(rezepte.NAME.fullmatch(i) for i in k), [i for i in k if not rezepte.NAME.fullmatch(i)]
assert k["spaghetti-dinkel"]["ober"] == "Spaghetti" and k["spaghetti-dinkel"]["stand"] == "da"
assert k["eier"]["stueck"] and k["eier"]["mindestens"] == 4 and k["eier"]["anzahl"] == 4
assert k["zwiebeln"]["stand"] == "leer" and k["salz"]["basis"]  # unter „# ergänzt“: leer
assert k["rapsoel"]["auch"] == ["Öl", "Pflanzenöl"] and k["gehackte-tomaten"]["stueck"]
for kaputt in ("Milch\n", "## Keller\nMilch\n", "## Brot\nToast\nToast\n"):
    try:
        vorrat.start_lesen(kaputt)
        raise AssertionError(kaputt)
    except ValueError:
        pass


def v():
    return vorrat.laden()["artikel"]


assert "Dinkel" in hole("/vorrat")[1].decode() and not os.path.exists(vorrat.DATEI)  # Lesen legt nichts an
assert 'aria-current="page">Vorrat' in hole("/vorrat")[1].decode()
zeile = hole("/vorrat/setzen", id="butter", stand="wenig", teil="1")[1].decode()
assert 'id="a-butter" class="artikel ist-wenig"' in zeile and v()["butter"]["liste"] == "auto"  # was ausgeht, kommt drauf
assert "wenig da" in hole("/einkauf")[1].decode()
hole("/vorrat/setzen", id="butter", stand="leer")
assert v()["butter"]["liste"] == "auto"
hole("/vorrat/setzen", id="butter", stand="da")
assert v()["butter"]["liste"] == ""  # wieder da: von selbst runter
hole("/vorrat/setzen", id="toast", liste="hand")
hole("/vorrat/setzen", id="toast", stand="wenig")
hole("/vorrat/setzen", id="toast", stand="da")
assert v()["toast"]["liste"] == "hand"  # von Hand drauf bleibt drauf
hole("/vorrat/setzen", id="eier", anzahl="3")
assert v()["eier"]["liste"] == "auto" and "3 da, mindestens 4" in hole("/einkauf")[1].decode()
for unsinn in ["²", "9" * 5000, "-1", "x"]:  # keine Zahl: wird uebergangen, statt Fehler 500
    assert status("/vorrat/setzen", id="eier", anzahl=unsinn) == 200 and v()["eier"]["anzahl"] == 3, unsinn[:9]
assert "name\">Zahnpasta<" not in hole("/einkauf")[1].decode()  # leer, aber nie da gewesen: nicht auf der Liste
hole("/vorrat/setzen", id="zwiebeln", stand="da")
hole("/vorrat/setzen", id="zwiebeln", stand="wenig")
assert v()["zwiebeln"]["liste"] == "auto"

# Abhaken schickt feste Werte: doppelt gesendet gleich einmal; Menge und Rueckgaengig
for _ in range(2):
    teil = hole("/einkauf/abhaken", id="eier", anzahl="4", altstand="leer", altanzahl="3", altliste="auto", teil="1")[1].decode()
assert v()["eier"]["anzahl"] == 4 and v()["eier"]["liste"] == "" and "Rückgängig" in teil and 'value="6"' in teil
hole("/einkauf/menge", id="eier", n="6", altstand="leer", altanzahl="3", altliste="auto")
assert v()["eier"]["anzahl"] == 9
hole("/vorrat/setzen", id="eier", stand="leer", anzahl="3", liste="auto")  # Rueckgaengig
assert v()["eier"]["anzahl"] == 3 and v()["eier"]["liste"] == "auto"
teil = hole("/einkauf/abhaken", id="zwiebeln", stand="da", altstand="wenig", altanzahl="0", altliste="auto", teil="1")[1].decode()
assert v()["zwiebeln"]["stand"] == "da" and "gekauft" not in teil  # keine Menge bei Stufen-Artikeln
hole("/einkauf/weg", id="toast", altstand="da", altanzahl="0", altliste="hand")
assert v()["toast"]["liste"] == "" and v()["toast"]["stand"] == "da"

# Vorschlaege: was nicht auf der Liste steht, alle versteckt bis zum Tipp ins Feld; Vorauswahl: wenig oder leer, hoechstens 12
import re  # noqa: E402
seite = hole("/einkauf")[1].decode()
assert re.search(r'name="id" value="aepfel" data-suche="äpfel" data-knapp hidden>Äpfel <span class="grund">leer<', seite), seite
assert re.search(r'name="id" value="toast"[^>]* hidden>', seite) and seite.count(" data-knapp hidden>") == 12
assert '<button class="zweit" name="id" value="eier"' not in seite  # steht schon drauf
assert hole("/einkauf/dazu", id="aepfel")[0].endswith("/einkauf") and v()["aepfel"]["liste"] == "hand"
assert '<button class="zweit" name="id" value="aepfel"' not in hole("/einkauf")[1].decode()
hole("/vorrat/setzen", id="aepfel", liste="nein")
assert status("/einkauf/dazu", id="gibts-nicht") == 404 and status("/einkauf/dazu", id="../x") == 404
hole("/einkauf/dazu", text="  feta ")
hole("/einkauf/dazu", text="Öl")  # Synonym
hole("/einkauf/dazu", text="Geschenkpapier <b>")
hole("/einkauf/dazu", text="Geschenkpapier <b>")
seite = hole("/einkauf")[1].decode()
assert v()["feta"]["liste"] == "hand" and v()["rapsoel"]["liste"] == "hand"
assert vorrat.laden()["einmalig"] == ["Geschenkpapier <b>"] and "Geschenkpapier &lt;b&gt;" in seite
hole("/einkauf/abhaken", name="Geschenkpapier <b>")
assert vorrat.laden()["einmalig"] == [] and "Geschenkpapier" not in hole("/vorrat")[1].decode()

# Artikel anlegen, aendern, loeschen
hole("/artikel/speichern", name="Tahini", ober="", bereich="Vorratsschrank", art="stufe", mindestens="1", auch="Sesampaste")
hole("/artikel/speichern", name="Tahini", ober="", bereich="Vorratsschrank", art="stufe", mindestens="1", auch="")
assert v()["tahini"]["auch"] == ["Sesampaste"] and "tahini-2" in v()
hole("/artikel/speichern", id="butter", name="Butter", ober="", bereich="Kühlschrank", art="stueck", mindestens="2", auch="")
assert v()["butter"]["stueck"] and v()["butter"]["anzahl"] == 2  # war da: zaehlt ab mindestens
assert status("/artikel?id=tahini") == 200 and status("/artikel") == 200 and status("/vorrat?f=fehlt&bearbeiten=1") == 200
# „Sorte von“: Oberbegriffe als Chips; steckt einer im Namen des neuen Artikels, sind er und sein Bereich vorausgewaehlt
vor = hole("/artikel?name=Vollkorn-Spaghetti")[1].decode()
assert 'id="ober" name="ober" list="obers" maxlength="60" value="Spaghetti"' in vor and "weil der Name „Spaghetti“ enthält" in vor
assert "<option selected>Vorratsschrank</option>" in vor and 'data-bereich="Vorratsschrank">Spaghetti</button>' in vor
for name in ["Tofu", "Spaghetti"]:  # kein Oberbegriff im Namen, oder der Name ist selbst einer: nichts vorausgewaehlt
    ohne = hole(f"/artikel?name={name}")[1].decode()
    assert 'maxlength="60" value="" aria-describedby' in ohne and "<option selected>Obst &amp; Gemüse</option>" in ohne, name
assert 'maxlength="60" value="" aria-describedby' in hole("/artikel?id=butter")[1].decode()  # vorhandene Artikel bleiben, wie sie sind
hole("/artikel/loeschen", id="tahini-2")
assert "tahini-2" not in v()
for weg, felder in [("/artikel?id=gibts-nicht", {}), ("/vorrat/setzen", {"id": "../x", "stand": "da"}), ("/einkauf/quatsch", {"id": "eier"})]:
    assert status(weg, **felder) == 404, weg
assert status("/vorrat/setzen", origin="http://fremd.example", id="butter", stand="leer") == 403
assert status("/artikel/speichern", name="X", bereich="Keller") == 500 and "x" not in v()

# --- Rezepte und Vorrat (Phase 2) ---
w = vorrat.woerter(k)


def bed(z):
    return sorted(bev or (k[ids[0]]["ober"] if len(ids) > 1 else ids[0]) for ids, bev in vorrat.bedarf(z, k, w))


for z, soll in [("1 Stück Knoblauchzehe", ["knoblauch"]), ("200 g Spaghetti", ["Spaghetti"]),
                ("160 g Dinkelspaghetti", ["spaghetti-dinkel"]), ("160 g Edamame-Spaghetti", ["spaghetti-edamame"]),
                ("150 g TK-Edamame, geschält", ["edamame"]), ("3 EL Pesto Tomate-Mandel", ["pesto-tomate-mandel"]),
                ("3 EL Pesto al Tartufo mit Pilzen", ["pesto-tartufo-mit-pilzen"]), ("600 g Süßkartoffeln", ["suesskartoffeln"]),
                ("600 g Kartoffeln, festkochend", ["kartoffeln-vorwiegend-festkochend"]), ("Salz, Pfeffer", ["pfeffer", "salz"]),
                ("100 g Basmatireis", ["reis-basmati"]), ("250 g Hähnchenbrustfilet", ["huehnchen"]),
                ("1 TL geräuchertes Paprikapulver", ["paprikapulver-geraeuchert"]), ("1 TL Paprikapulver", ["Paprikapulver"]),
                ("2 Stück Servietten", []), ("1 Rolle Klopapier", [])]:  # Klopapier ist nicht essbar
    assert bed(z) == soll, (z, bed(z))
for z, soll in [("0,5 Bund Petersilie (frisch), gehackt", "Petersilie"), ("2 EL Trinkgeld, gern großzügig", "Trinkgeld"),
                ("Salz", "Salz"), ("1 Stück Lieferbote mit Orientierungssinn", "Lieferbote mit Orientierungssinn")]:
    assert vorrat.kern(z) == soll, (z, vorrat.kern(z))
beginn = time.time()
vorrat.kern("(" * 200_000)  # so lang darf ein POST sein; ungebremst 16 s je Aufruf, mehrmals je Seite
assert time.time() - beginn < 1, time.time() - beginn

N2 = NAME + "-2"  # Spaghetti, Zucchini und Bio-Zitrone; Zitronen sind leer
liste = hole("/rezepte")[1].decode()
assert '<li class="grau" data-suche="' in liste and '"><a href="/rezept?d=' + N2 in liste and "fehlt: Zitronen" in liste
assert "Kein Rezept passt" in hole("/rezepte?k=1")[1].decode()  # nur kochbare: ueberall fehlen die Zitronen
rz = hole(f"/rezept?d={N2}")[1].decode()
assert '<span class="marke m-fehlt">fehlt</span>' in rz and "Fehlendes auf die Liste (1)" in rz and 'm-da">da<' in rz
assert hole("/einkauf/rezept", d=N2)[0].endswith(f"/rezept?d={N2}")
assert v()["zitronen"]["liste"] == "hand" and "für Zucchini-Pasta mit Zitrone" in hole("/einkauf")[1].decode()
rz = hole(f"/rezept?d={N2}")[1].decode()
assert "Fehlendes auf" not in rz and "steht auf der" in rz
hole("/einkauf/abhaken", id="zitronen", stand="da", altstand="leer", altanzahl="0", altliste="hand")
assert v()["zitronen"]["liste"] == "" and "fuer" not in v()["zitronen"]
kochbar = hole("/rezepte?k=1")[1].decode()
assert f'href="/rezept?d={N2}"' in kochbar and '<a href="/rezepte" aria-current="true">Kochbar</a>' in kochbar
start = hole("/")[1].decode()
assert 'aria-current="page">Start' in start and start.index(f"/rezept?d={N2}") > start.index("Jetzt kochbar")
assert "Sachen auf der Liste" in start

hole("/speichern", text="# Probe\n## Zutaten\n- 1 Bund Petersilie\n- 2 Stück Servietten\n- 1 Kresse\n## Zubereitung\n1. Los.\n")
assert "Zutaten ohne Artikel" not in hole("/")[1].decode() and "3 Zutaten ohne Artikel" in hole("/rezepte")[1].decode()
offen = hole("/zuordnen")[1].decode()
assert all(f'<p class="titel">{x}</p>' in offen for x in ("Petersilie", "Servietten", "Kresse")) and "in Probe" in offen
assert 'href="/artikel?name=Kresse&kern=Kresse&zurueck=zuordnen"' in offen  # umbenannt bleibt die Zutat Synonym
hole("/zuordnen/egal", kern="Servietten")
hole("/zuordnen/egal", kern="Servietten")  # doppelt getippt steht es nur einmal drin
assert vorrat.laden()["egal"] == ["servietten"]
hole("/zuordnen/zuordnen", kern="Petersilie", text="blattsalat")
assert "Petersilie" in v()["blattsalat"]["auch"]
url, neu = hole("/zuordnen/zuordnen", kern="Kresse", text="Gartenkresse")  # gibt es nicht: neuer Artikel, Name vorbelegt
assert url.endswith("/artikel?name=Gartenkresse&kern=Kresse&zurueck=zuordnen") and 'value="Gartenkresse"' in neu.decode()
assert 'name="kern" value="Kresse"' in neu.decode()
assert hole("/artikel/speichern", name="Gartenkresse", ober="", bereich="Obst & Gemüse", art="stufe", zurueck="zuordnen",
            kern="Kresse")[0].endswith("/zuordnen")
assert v()["gartenkresse"]["auch"] == ["Kresse"]  # die Zutat wird Synonym des neuen Artikels
assert "Alle Zutaten sind zugeordnet" in hole("/zuordnen")[1].decode()
assert vorrat.pruefer()(rezepte.lesen(rezepte.text("probe"))[0])["zeilen"] == ["da", "egal", "fehlt"]

je = vorrat.zutaten_je_schritt(rezepte.lesen(rezepte.text(N2))[0])
assert je[0] == [0] and je[1] == [1], je  # Spaghetti-Schritt: Spaghetti, Zucchini-Schritt: Zucchini
with open(vorrat.DATEI, "w") as f:
    f.write("{kaputt")
assert vorrat.zutaten_je_schritt(rezepte.lesen(rezepte.text(N2))[0]) == [[0], [1]]  # nur Namensvergleich
os.remove(vorrat.DATEI)

# --- Kochen und Vorlieben (Phase 3) ---
koch = hole("/kochen")[1].decode()
assert 'id="w-zucchini"' in koch and 'id="w-klopapier"' not in koch and 'id="w-salz"' not in koch  # nicht essbar, Basis
assert 'id="w-frischkaese"' not in koch and 'class="leiste kochen-leiste"' not in koch  # leer: nicht zum Auswaehlen
koch = hole("/kochen?w=zucchini&w=gibts-nicht")[1].decode()
assert 'id="w-zucchini" checked' in koch and f'href="/rezept?d={N2}"' in koch and "Rezepte mit allem davon" in koch
assert 'href="/neu?w=zucchini"' in koch
teil = hole("/kochen?teil=1&w=zucchini&w=feta")[1].decode()
assert not teil.startswith("<!doctype") and "Kein eigenes Rezept" in teil and N2 not in teil  # nur mit allem davon, Feta fehlt
assert f"/rezept?d={N2}" in hole("/kochen?teil=1&w=zucchini&w=spaghetti-dinkel")[1].decode()  # jede Sorte zählt
neu = hole("/neu?w=zucchini&w=feta")[1].decode()
assert "DAMIT KOCHEN: Zucchini, Feta" in neu and 'value="etwas mit Zucchini, Feta"' in neu and "EINKAUFEN: Höchstens 2" in neu
da = next(z for z in neu.splitlines() if z.startswith("ZUTATEN:"))  # aus „Kochen“: der Vorrat steht schon im Prompt
assert "Spaghetti (Dinkel)" in da and "Zucchini" in da and "Salz" not in da and "Klopapier" not in da
assert "Frischkäse" not in da.split(": ")[1].split(", ") and 'id="zutaten-0" value="' + da[9:] + '" checked' in neu  # leer: nicht im Vorrat
assert 'id="einkaufen-0" value="Höchstens 2 Zutaten dürfen nicht unter ZUTATEN stehen, nenne sie im Tipp." checked' in neu
neu = hole("/neu")[1].decode()
assert "ZUTATEN: &lt;" in neu and "replace(/^ZUTATEN:" in neu and 'name="einkaufen"' not in neu and " checked" not in neu
alle = re.search(r'id="zutaten-1" value="([^"]*)"', neu)[1]
assert "Frischkäse" in alle.split(", ") and "Zucchini" in alle and "Salz" not in alle and "Klopapier" not in alle
assert 'id="zutaten-2" value="frei"' in neu
assert "DAMIT KOCHEN:" not in hole("/neu")[1].decode() and "VORLIEBEN:" not in hole("/neu")[1].decode()
assert "Vorlieben hinterlegen" in hole("/neu")[1].decode() and status("/vorlieben") == 200
assert hole("/vorlieben", text="  Mögen nicht: <Koriander>  ")[0].endswith("/neu")
neu = hole("/neu")[1].decode()
assert "VORLIEBEN:\nMögen nicht: &lt;Koriander&gt;\n\nGib das Rezept" in neu and "Eure Vorlieben" in neu
assert "Zucchini-Pasta mit Zitrone" in neu.split("VORHANDEN: ")[1].splitlines()[0]  # damit nichts doppelt kommt
assert "ANZAHL: &lt;" in neu and 'name="anzahl" id="anzahl-1" value="3"' in neu and "replace(/^ANZAHL:" in neu
assert "ZEIT: <" not in neu and 'name="zeit"' in neu  # Platzhalter maskiert, Knoepfe da
assert status("/vorlieben", origin="http://fremd.example", text="x") == 403

# Balkonwert von Home Assistant (dash.py): HA schickt ohne Origin, fremde Webseiten duerfen nichts setzen
assert hole("/balkon", origin=None, wert="5.5")[1] == b"ok" and dash.balkon() == 5.5
assert status("/balkon", origin=None, wert="unavailable") == 400 and dash.balkon() == 5.5
assert status("/balkon", origin="http://fremd.example", wert="30") == 403 and dash.balkon() == 5.5
# Von unterwegs (nginx, https): gleicher Host mit https gilt als eigener Origin, fremder https-Origin nicht
assert status("/balkon", origin=BASIS.replace("http:", "https:"), wert="unsinn") == 400
assert status("/balkon", origin="https://fremd.example", wert="30") == 403 and dash.balkon() == 5.5

# --- Phase 4: einkauf.json, Gekocht, Liste zum Auffrischen, Kindle-Kachel ---
import json  # noqa: E402
hole("/vorrat/setzen", id="eier", anzahl="3")
assert 'class="unter">wenig, mindestens 4</span>' in hole("/vorrat")[1].decode()
daten = json.loads(hole("/einkauf.json")[1])
assert daten["anzahl"] == len(daten["artikel"]) and {"name": "Eier", "bereich": "Kühlschrank", "grund": "3 da, mindestens 4"} in daten["artikel"]
assert daten == {"anzahl": len(vorrat.einkaufsliste()), "artikel": vorrat.einkaufsliste()}
teil = hole("/einkauf?teil=1")[1].decode()
assert not teil.startswith("<!doctype") and "name\">Eier<" in teil and 'id="listen"' in hole("/einkauf")[1].decode()
assert 'href="/gekocht?d=' + N2 in hole(f"/rezept?d={N2}")[1].decode()
gek = hole(f"/gekocht?d={N2}")[1].decode()
assert 'id="a-zucchini"' in gek and 'id="a-zitronen"' in gek and 'id="a-spaghetti-' in gek and 'id="a-salz"' not in gek
assert status("/gekocht?d=gibts-nicht") == 404
z = hole("/vorrat/setzen", id="zucchini", stand="wenig", teil="1")[1].decode()  # derselbe Knopf wie im Vorrat
assert "ist-wenig" in z and v()["zucchini"]["liste"] == "auto"
hole("/heute", d=N2, an="1")
Image.open(io.BytesIO(dash.zeichnen("42", datetime.now().astimezone()))).save(os.path.join(rezepte.DATEN, "kachel.png"))

# --- Kindle-Browser: Rezeptliste, ein Rezept auf einem Bildschirm, Fehlendes auf die Liste, Gekocht ---
kl = hole("/kindle")[1].decode()
assert f'<a href="/kindle/rezept?d={N2}">Zucchini-Pasta mit Zitrone <span class="werte">530 kcal, E 19 g, F 16,5 g</span>' in kl
assert "<h2>Abendessen</h2>" in kl and "<h2>Weitere</h2>" in kl
hole("/vorrat/setzen", id="zitronen", stand="leer")
kr = hole(f"/kindle/rezept?d={N2}&portionen=4")[1].decode()
# zwei Spalten, von oben nach unten: links Spaghetti und Zucchini, rechts die Zitrone; umgerechnet, maskiert, Fehlendes markiert
assert ('<tr><td>400 g Spaghetti</td><td>2 Stück Bio-Zitrone &lt;scharf&gt; &amp; frisch <span class="fehlt">fehlt</span></td></tr>'
        '<tr><td>2 Stück Zucchini</td><td></td></tr>') in kr, kr
assert '<button name="portionen" value="3"' in kr and '<button name="portionen" value="5"' in kr  # GET-Formular
assert "Umgerechnet von 2 Portionen" in kr and '<form method="get" action="/kindle/gekocht">' in kr
assert "Fehlendes auf die Liste (1)" in kr and '<input type="hidden" name="portionen" value="4">' in kr
assert 'value="13" aria-label="Eine Portion mehr" disabled>+' in hole(f"/kindle/rezept?d={N2}&portionen=12")[1].decode()
assert not any(x in kr for x in ("Heute kochen", "Kochmodus", "Bearbeiten", "Löschen"))
assert hole("/kindle/fehlendes", d=N2, portionen="4")[0].endswith(f"/kindle/rezept?d={N2}&portionen=4")
assert v()["zitronen"]["liste"] == "hand" and "steht auf der Einkaufsliste" in hole(f"/kindle/rezept?d={N2}")[1].decode()
kg = hole(f"/kindle/gekocht?d={N2}")[1].decode()
assert 'id="a-zucchini"' in kg and 'id="a-salz"' not in kg and f'<input type="hidden" name="d" value="{N2}">' in kg
assert hole("/kindle/gekocht", d=N2, id="zucchini", stand="leer")[0].endswith(f"/kindle/gekocht?d={N2}#a-zucchini")
assert v()["zucchini"]["stand"] == "leer"
for s in (kl, kr, kg):  # was der alte Browser nicht kann; jedes Formular fuehrt auf eine Kindle-Seite zurueck
    assert not any(x in s for x in ("var(--", "flex", "grid", "=>", "const ", "let ", "async", 'class="knopf')), s
    assert all(teil.startswith("/kindle/") for teil in s.split(' action="')[1:]), s
for felder in [{"d": "../x"}, {"d": N2 + "\r\nX-Kopf: 1"}, {"d": N2, "id": "gibts-nicht"}]:
    assert status("/kindle/gekocht", stand="da", **{"id": "zucchini", **felder}) == 404, felder
assert v()["zucchini"]["stand"] == "leer"  # nichts geaendert
assert status("/kindle/fehlendes", origin="http://fremd.example", d=N2) == 403 and status("/kindle/heute", d=N2) == 404
assert status("/kindle/rezept?d=gibts-nicht") == 404 and status("/kindle/gekocht?d=../x") == 404 and status("/kindle/x") == 404

# --- Mehrere Rezepte auf einmal: Sammel-Vorschau, nur Gueltiges ist waehlbar, /speichern nimmt mehrere Felder „text“ ---
sammel = hole("/vorschau", text=DREI_BLOECKE)[1].decode()
assert "<h1>3 Rezepte</h1>" in sammel and sammel.count('type="checkbox" name="text"') == 3
assert sammel.count('" checked><label') == 2 and sammel.count('" disabled><label') == 1 and "Zubereitung fehlt" in sammel
assert 'value="# Zweites\nMahlzeit: Abendessen' in sammel and "&lt;scharf&gt;" in sammel and "<scharf>" not in sammel
assert "<h1>Vorschau</h1>" in hole("/vorschau", text=EIN_BLOCK.replace(R2, ""))[1].decode()  # ein Rezept: wie bisher
assert "<h1>Bearbeiten</h1>" in hole("/vorschau", d=N2, text=text + R2)[1].decode()  # Bearbeiten teilt nie
vorher = len(rezepte.alle())
url, seite = hole("/speichern", text=[R2, "# Kaputt", R2.replace("Zweites", "Viertes").replace("\n", "\r\n")])
assert url.endswith("/rezepte?gespeichert=2") and "2 Rezepte gespeichert." in seite.decode() and len(rezepte.alle()) == vorher + 2
assert rezepte.lesen(rezepte.text("viertes"))[0]["zutaten"][0] == "200 g Spaghetti"  # Browser schicken Zeilen mit \r\n
assert "Rezepte gespeichert." not in hole("/rezepte?gespeichert=%3Cb%3E")[1].decode()
assert len(rezepte.alle()) == vorher + 2 and hole("/speichern", text=["# A", "# B"])[0].endswith("gespeichert=0")

with open(vorrat.DATEI, "w") as f:
    f.write("{kaputt")
assert status("/vorrat") == 500 and status("/vorrat/setzen", id="butter", stand="da") == 500
assert open(vorrat.DATEI).read() == "{kaputt"  # eine kaputte Datei wird nie ueberschrieben
assert status("/rezepte") == 200 and status(f"/rezept?d={N2}") == 200 and status("/rezeptbuch.epub") == 200  # Rezepte bleiben
assert status("/kindle") == 200 and status(f"/kindle/rezept?d={N2}") == 200  # auch am Kindle
assert status("/neu?w=zucchini") == 200 and status("/kochen") == 500
assert "Einkaufsliste nicht lesbar" in hole("/")[1].decode()  # auch die Startseite bleibt
Image.open(io.BytesIO(dash.zeichnen("42", datetime.now().astimezone())))  # Kindle-Bild auch ohne lesbare Liste
print("ok", os.path.join(rezepte.DATEN, "kachel.png"))
