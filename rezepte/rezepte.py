"""Rezept-Seite der Kuechen-App: Rezepte als Markdown in DATEN/rezepte, ohne eigenen Login
(gedacht fuers Heimnetz; wer sie von aussen erreichbar macht, braucht davor einen eigenen Riegel mit Anmeldung).

GET  /                   Startseite (vorrat.start_seite)
GET  /rezepte?m=mittag|abend&t=TAG&k=1  Liste mit Naehrwerten; Filter: Mahlzeit, Tags (alle muessen passen), nur
                         kochbare, dazu ein Suchfeld; Rezepte, fuer die etwas fehlt, grau
GET  /neu?w=ID&w=ID      Prompt kopieren (auch fuer mehrere Rezepte auf einmal), Antwort einfuegen; w: Auswahl aus
                         „Kochen“ (DAMIT KOCHEN, SONST DA)
GET  /vorlieben          gemeinsame Vorlieben, stehen in jedem Prompt
GET  /rezept?d=NAME      ein Rezept mit Heute kochen / Bearbeiten / Loeschen
GET  /bearbeiten?d=NAME  Text aendern, mit Vorschau
GET  /kochmodus?d=NAME&portionen=N&schritt=K  Schritt fuer Schritt kochen, Timer, Display bleibt an
GET  /rezeptbuch.epub    alle Rezepte als EPUB fuer KOReader
GET  /kindle             Rezeptliste fuer den Browser des Kindle (nur im Heimnetz, kindle_seite)
GET  /kindle/rezept?d=NAME&portionen=N  ein Rezept auf einem Bildschirm, mit Fehlendes auf die Liste und Gekocht
GET  /kindle/gekocht?d=NAME  Gekocht fuer den Kindle (vorrat.kindle_gekocht)
POST /kindle/fehlendes, /kindle/gekocht  wie /einkauf/rezept und /vorrat/setzen, zurueck auf die Kindle-Seite
POST /vorschau, /speichern, /heute, /loeschen, /vorlieben  (Antwort mit mehreren Rezepten: Sammel-Vorschau, /speichern
     nimmt dann mehrere Felder „text“)
/vorrat, /einkauf, /artikel, /zuordnen, /kochen...  Vorrat, Einkaufsliste, Zuordnung und Kochen in vorrat.py

Seiten liefern (typ, daten) oder (typ, daten, 303, ziel) fuer Handler.antwort in dash.py.
Unbekannte Pfade und Rezepte heben FileNotFoundError (-> 404).
"""
import html
import io
import os
import re
import time
import zipfile
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlencode

HIER = os.path.dirname(os.path.abspath(__file__))
DATEN = os.environ.get("DATEN", os.path.join(HIER, "daten"))
ORDNER = os.path.join(DATEN, "rezepte")
PAPIERKORB = os.path.join(ORDNER, "papierkorb")
HEUTE = os.path.join(DATEN, "heute.txt")
VORLIEBEN = os.path.join(DATEN, "vorlieben.txt")
BEISPIEL = """Wir sind zu zweit.
Mögen: mediterran, asiatisch, viel Gemüse
Mögen nicht: Koriander, Rosenkohl
Fleisch höchstens zweimal pro Woche, lieber Hähnchen
Mindestens 30 g Eiweiß pro Portion
Geräte: Backofen, Airfryer
Unter der Woche höchstens 30 min"""
NAME = re.compile(r"[a-z0-9-]{1,60}")
ABSCHNITTE = ("zutaten", "zubereitung", "tipp")
MAHLZEITEN = (("mittag", "Mittagessen"), ("abend", "Abendessen"))
# (Schluessel, Muster, Name im Rezept, Einheit, Kuerzel im Titel); Zahl darf „32,5“ sein
WERTE = (("kcal", r"kcal", "Kalorien", "kcal", ""), ("eiweiss", r"g\s*(?:eiwei|protein)", "Eiweiß", "g", "E"),
         ("fett", r"g\s*fett", "Fett", "g", "F"), ("kh", r"g\s*kohlenhydrat", "Kohlenhydrate", "g", ""))
with open(os.path.join(HIER, "prompt.txt"), encoding="utf-8") as f:
    PROMPT = f.read()
with open(os.path.join(HIER, "stil.css"), encoding="utf-8") as f:
    STIL = f.read()


def saeubern(text):
    """Codeblock-Zaeune und Geplauder vor dem Titel entfernen."""
    zeilen = [z.rstrip() for z in text.splitlines() if not z.strip().startswith("```")]
    start = next((i for i, z in enumerate(zeilen) if z.lstrip().startswith("# ")), 0)
    return "\n".join(zeilen[start:]).strip() + "\n"


def teilen(text):
    """Antwort mit einem oder mehreren Rezepten -> [Rezepttext], hoechstens 10. Gibt es Codebloecke, zaehlt nur ihr
    Inhalt (Geplauder davor, dazwischen und danach faellt weg); getrennt wird an jeder Zeile „# Titel“."""
    bloecke = re.findall(r"^```[^\n]*\n(.*?)^```", text, re.S | re.M) or [text]
    teile = [t for b in bloecke for t in re.split(r"^(?=# )", b, flags=re.M) if t.startswith("# ")]
    return [saeubern(t) for t in teile[:10]] or [saeubern(text)]


def lesen(text):
    """Markdown im Format aus prompt.txt -> (rezept, fehler, hinweise). Fehler verhindern das Speichern."""
    r = {"titel": "", "portionen": "", "zeit": "", "tags": [], "mahlzeit": [], "naehrwerte": {},
         "zutaten": [], "zubereitung": [], "tipp": ""}
    hinweise = []
    abschnitt = None
    for zeile in text.splitlines():
        s = zeile.strip().replace("**", "")
        if not s or s.startswith("```"):
            continue
        if s.startswith("# ") and not r["titel"]:
            r["titel"], abschnitt = s[2:].strip(), None
        elif s.startswith("## "):
            abschnitt = (s[3:].lower().split() or [""])[0].strip(":")
            if abschnitt not in ABSCHNITTE:
                hinweise.append(f"Abschnitt „{s[3:].strip()}“ wird nicht angezeigt.")
        elif abschnitt is None and re.match(r"(portionen|zeit|tags|mahlzeit|n(ä|ae)hrwerte)\b[^:]{0,20}:", s, re.I):
            k, v = s.split(":", 1)
            k = k.lower().split()[0]
            if k == "tags":
                r[k] = [t.strip() for t in v.split(",") if t.strip()]
            elif k == "mahlzeit":
                beide = re.search(r"beide", v, re.I)
                r[k] = [m for m, _ in MAHLZEITEN if beide or m in v.lower()]
            elif k.startswith("n"):
                v = v[:200]  # die Suche waechst mit dem Quadrat der Laenge: 10.000 Ziffern brauchten 9 s
                r["naehrwerte"] = {w: m.group(1) for w, muster, *_ in WERTE
                                   if (m := re.search(r"(\d+(?:[.,]\d+)?)\s*" + muster, v, re.I))}
            else:
                r[k] = v.strip()
        elif abschnitt == "zutaten":
            r["zutaten"].append(re.sub(r"^[-*•]\s*", "", s))
        elif abschnitt == "zubereitung":
            r["zubereitung"].append(re.sub(r"^\d+[.)]\s*", "", s))
        elif abschnitt == "tipp":
            r["tipp"] = f"{r['tipp']} {s}".strip()
        elif abschnitt is None:
            hinweise.append(f"Zeile wird nicht angezeigt: „{s[:50]}“")
    fehler = [meldung for da, meldung in [
        (r["titel"], "Titel fehlt: Die erste Zeile muss mit „# “ beginnen."),
        (r["zutaten"], "Zutaten fehlen: Abschnitt „## Zutaten“ mit Zeilen „- …“."),
        (r["zubereitung"], "Zubereitung fehlt: Abschnitt „## Zubereitung“ mit Zeilen „1. …“."),
    ] if not da]
    hinweise = [f"„{k}:“ fehlt." for k in ("Mahlzeit", "Portionen", "Zeit", "Tags") if not r[k.lower()]] + hinweise
    if "kcal" not in r["naehrwerte"]:
        hinweise.insert(0, "„Nährwerte pro Portion: … kcal, … g Eiweiß, … g Fett“ fehlt.")
    return r, fehler, hinweise


ZAHL = r"\d+/\d+|\d+(?:[.,]\d+)?(?:\s?[½¼¾])?|[½¼¾]"
MENGE = re.compile(rf"({ZAHL})(?:\s*[–-]\s*({ZAHL}))?")
EI = re.compile(r"(?:\S+\s+)?Ei(?:er|gelb|weiß)?\b")  # „Eisbergsalat“ zählt nicht


def zahl_lesen(s):
    brueche = {"½": .5, "¼": .25, "¾": .75}
    return sum(brueche.get(t) or (int(t.split("/")[0]) / int(t.split("/")[1]) if "/" in t else float(t.replace(",", ".")))
               for t in re.findall(r"\d+/\d+|\d+(?:[.,]\d+)?|[½¼¾]", s))


def runden(x, schritt):
    return int(x / schritt + .5 + 1e-9) * schritt  # kaufmännisch, +1e-9 gegen Gleitkomma-Rauschen


def skalieren(zeile, faktor):
    """Eine Zutatenzeile (ohne „- “) auf andere Portionen umrechnen. Nicht Rechenbares bleibt, wie es ist."""
    m = MENGE.match(zeile)
    if not m or faktor == 1:
        return zeile
    try:
        return skaliert(zeile, m, faktor)
    except (ZeroDivisionError, OverflowError):  # „1/0 TL“ oder 400 Ziffern
        return zeile


def skaliert(zeile, m, faktor):
    rest = zeile[m.end():]
    u = re.match(r"\s*(\S+)", rest)
    einheit = u.group(1) if u else ""
    if einheit in ("Prise", "Prisen"):
        return zeile
    werte = [zahl_lesen(g) for g in m.groups() if g]
    if einheit in ("g", "kg", "ml", "l"):
        grund = "g" if einheit.endswith("g") else "ml"
        n = [w * faktor * (1000 if einheit in ("kg", "l") else 1) for w in werte]
        n = [max(.1, runden(x, .1 if x < 1 else 1 if x < 10 else 5 if x < 100 else 10)) for x in n]  # nie „0 g“
        gross = max(n) >= 1000
        zahlen = [f"{x / 1000 if gross else x:g}".replace(".", ",") for x in n]
        neu, rest = ("k" + grund if gross and grund == "g" else "l" if gross else grund), rest[u.end():]
        return "–".join(zahlen) + " " + neu + rest
    schritt, mini = (1, 1) if EI.match(rest.lstrip()) else (.5, .5)
    zahlen = []
    for w in werte:
        x = max(mini, runden(w * faktor, schritt))
        zahlen.append(("" if int(x) == 0 else str(int(x))) + (" " if int(x) and x % 1 else "") + ("½" if x % 1 else ""))
    return "–".join(zahlen) + rest


def umgerechnet(r, portionen):
    """Rezept auf andere Portionen (Text aus der Adresse) umrechnen; sonst r selbst."""
    alt = r["portionen"]
    zahl = re.compile(r"[0-9]{1,2}")  # wie regler(); isdigit() liesse auch „²“ und 5000 Ziffern durch
    if not (zahl.fullmatch(portionen) and 1 <= int(portionen) <= 12 and zahl.fullmatch(alt) and 0 < int(alt) != int(portionen)):
        return r
    f = int(portionen) / int(alt)
    return dict(r, zutaten=[skalieren(z, f) for z in r["zutaten"]], portionen=str(int(portionen)), basis=int(alt))


def name_aus(titel):
    s = titel.lower().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}))
    return re.sub(r"[^a-z0-9]+", "-", s)[:50].strip("-") or "rezept"


def pfad(name):
    """Nur Namen wie „pasta-mit-zucchini“, damit niemand aus dem Ordner herauskommt."""
    if not NAME.fullmatch(name):
        raise FileNotFoundError(name)
    return os.path.join(ORDNER, name + ".md")


def text(name):
    with open(pfad(name), encoding="utf-8") as f:
        return f.read()


def schreiben(p, inhalt):
    with open(p + ".neu", "w", encoding="utf-8") as f:
        f.write(inhalt)
    os.replace(p + ".neu", p)


def alle():
    """[(name, rezept)], nach Titel sortiert."""
    os.makedirs(ORDNER, exist_ok=True)
    liste = [(d[:-3], lesen(text(d[:-3]))[0]) for d in os.listdir(ORDNER)
             if d.endswith(".md") and NAME.fullmatch(d[:-3])]
    return sorted(liste, key=lambda x: name_aus(x[1]["titel"]))


def speichern(name, inhalt):
    """Ein bestehendes Rezept ueberschreiben oder ein neues anlegen, ohne ein anderes zu ueberschreiben."""
    if not (NAME.fullmatch(name) and os.path.exists(pfad(name))):
        os.makedirs(ORDNER, exist_ok=True)
        basis = name = name_aus(lesen(inhalt)[0]["titel"])
        n = 1
        while os.path.exists(pfad(name)):
            n += 1
            name = f"{basis}-{n}"
    schreiben(pfad(name), inhalt)
    return name


def heute_name():
    try:
        with open(HEUTE, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


def heute():
    """Das Rezept fuer die Kachel „Heute kochen“ oder None."""
    try:
        return lesen(text(heute_name()))[0]
    except FileNotFoundError:
        return None


def kindle_da():
    """Hat in den letzten zwei Tagen ein Kindle sein Bild geholt? dash.py schreibt dann akku.csv. Ohne Kindle steht
    auf der Handy-Seite nichts von ihm."""
    try:
        return time.time() - os.path.getmtime(os.path.join(DATEN, "akku.csv")) < 2 * 86400
    except OSError:
        return False


def heute_setzen(name, an):
    """Der Knopf schickt den Zielzustand, nie „umschalten“: doppelt oder von einer alten Seite gesendet ist harmlos."""
    if not os.path.exists(pfad(name)):
        raise FileNotFoundError(name)
    if an or heute_name() == name:
        schreiben(HEUTE, name if an else "")


def loeschen(name):
    os.makedirs(PAPIERKORB, exist_ok=True)
    os.replace(pfad(name), os.path.join(PAPIERKORB, f"{name}-{datetime.now():%Y%m%d-%H%M%S}.md"))
    if heute_name() == name:
        schreiben(HEUTE, "")


def e(s):
    return html.escape(s)


def kurz(r):
    """Naehrwerte fuer Titelzeilen, z. B. „650 kcal, E 32 g, F 20 g“; leer ohne kcal."""
    w = r["naehrwerte"]
    if "kcal" not in w:
        return ""
    return ", ".join([f"{w['kcal']} kcal"] + [f"{kz} {w[k]} g" for k, _, _, _, kz in WERTE if kz and k in w])


def mahlzeit_text(r):
    return " und ".join(n for m, n in MAHLZEITEN if m in r["mahlzeit"])


def rezept_html(r, marken=None, regler=""):
    """Fragment fuer Webseite und EPUB, deshalb gueltiges XHTML; ohne CSS (KOReader) eine schlichte Tabelle.
    marken: fertiges HTML je Zutat (Vorrat), regler: Portionen − 2 +, beides nur auf der Webseite.
    Hat r eine „basis“ (umgerechnet()), stehen Hinweise an Zutaten und Zubereitung."""
    marken = marken or [""] * len(r["zutaten"])
    b = r.get("basis")
    meta = ", ".join(x for x in (mahlzeit_text(r), r["portionen"] and f"{r['portionen']} Portionen", r["zeit"]) if x)
    teile = [f"<h1>{e(r['titel'])}</h1>"]
    if meta:
        teile.append(f'<p class="meta">{e(meta)}</p>')
    if r["naehrwerte"]:
        teile.append('<table class="naehrwerte"><caption>Nährwerte pro Portion, geschätzt</caption>' + "".join(
            f'<tr><th scope="row">{name}</th><td><span class="zahl">{e(r["naehrwerte"][k])}</span> {einheit}</td></tr>'
            for k, _, name, einheit, _ in WERTE if k in r["naehrwerte"]) + "</table>")
    if r["tags"]:
        teile.append('<p class="tags">' + " ".join(f'<span class="tag">{e(t)}</span>' for t in r["tags"]) + "</p>")
    teile.append(f'<h2 id="zutaten">Zutaten</h2>{regler}<ul class="zutaten">'
                 + "".join(f"<li>{e(z)}{m}</li>" for z, m in zip(r["zutaten"], marken)) + "</ul>")
    if b:
        teile.append(f'<p class="erklaerung">Umgerechnet von {b} Portionen. Gewürze nach Geschmack anpassen.</p>')
    teile.append("<h2>Zubereitung</h2>" + (f'<p class="erklaerung">Mengen im Text gelten für {b} Portionen.</p>' if b else "")
                 + '<ol class="schritte">' + "".join(f"<li>{e(s)}</li>" for s in r["zubereitung"]) + "</ol>")
    if r["tipp"]:
        teile.append(f'<h2>Tipp</h2><p class="tipp">{e(r["tipp"])}</p>')
    return "\n".join(teile)


SKRIPT = """
function kopieren() {
  const w = document.getElementById('wunsch').value.trim();
  const m = document.querySelector('input[name=mahlzeit]:checked');
  const p = document.getElementById('prompt').value
    .replace(/^WUNSCH:.*$/m, z => w ? 'WUNSCH: ' + w : z)
    .replace(/^MAHLZEIT:.*$/m, z => m ? 'MAHLZEIT: ' + m.value : z)
    .replace(/^ANZAHL:.*$/m, z => wahl('anzahl') ? 'ANZAHL: ' + wahl('anzahl') : z)
    .replace(/^ZEIT:.*$/m, z => wahl('zeit') ? 'ZEIT: ' + wahl('zeit') : z)
    .replace(/^PORTIONEN:.*$/m, z => wahl('portionen') ? 'PORTIONEN: ' + wahl('portionen') : z)
    .replace(/^ZUTATEN:.*$/m, z => wahl('zutaten') ? 'ZUTATEN: ' + wahl('zutaten') : z)
    .replace(/^EINKAUFEN:.*$/m, z => wahl('einkaufen') ? 'EINKAUFEN: ' + wahl('einkaufen') : z);
  // navigator.clipboard gibt es nur ueber HTTPS; im Heimnetz (HTTP) bleibt execCommand
  if (navigator.clipboard) return navigator.clipboard.writeText(p).then(() => melden(true), () => melden(false));
  const t = document.createElement('textarea');
  t.value = p; t.setAttribute('readonly', ''); t.style.cssText = 'position:fixed;left:-9999px;font-size:12pt';
  document.body.append(t); t.select(); t.setSelectionRange(0, p.length);
  let ok = false; try { ok = document.execCommand('copy'); } catch (e) {}
  t.remove(); melden(ok);
}
function wahl(name) {
  const x = document.querySelector('input[name=' + name + ']:checked');
  return x ? x.value : '';
}
function melden(ok) {
  document.getElementById('status').textContent =
    ok ? 'Kopiert ✓' : 'Ging nicht. Unter „Prompt ansehen“ den Text lang drücken und kopieren.';
}
"""

ZURUECK = '<p><a class="zurueck" href="/rezepte">Alle Rezepte</a></p>'


def seite(titel, inhalt, oben="/rezepte"):
    """Ganze Seite mit der Leiste unten; oben ist der Reiter, der hervorgehoben wird. oben=None: ohne Leiste."""
    aktuell = ' aria-current="page"'
    leiste = "".join(f'<a href="{weg}"{aktuell if weg == oben else ""}>{name}</a>'
                     for weg, name in (("/", "Start"), ("/rezepte", "Rezepte"), ("/vorrat", "Vorrat"), ("/einkauf", "Einkauf"), ("/kochen", "Kochen")))
    return "text/html; charset=utf-8", f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(titel)}</title><style>{STIL}</style></head><body><main class="seite">
{inhalt}
</main>{f'<nav class="unten" aria-label="Hauptmenü">{leiste}</nav>' if oben else ""}</body></html>""".encode()


def weiter(ziel):
    return "text/plain", b"", 303, ziel


def zeile(n, r, h, p):
    """Eine Zeile der Rezeptliste; p ist die Pruefung gegen den Vorrat (fehlt etwas, wird die Zeile grau)."""
    werte = r["naehrwerte"]
    fehlt = p["fehlt"]
    rest = ", ".join(f"{kz} {werte[k]} g" for k, _, _, _, kz in WERTE if kz and k in werte)
    rechts = (f'<span class="werte"><span class="kcal"><span class="zahl">{e(werte["kcal"])}</span> kcal</span>'
              f'<span class="ef">{e(rest)}</span></span>') if "kcal" in werte else '<span class="werte leer">ohne Nährwerte</span>'
    info = "".join(f'<span class="tag">{e(t)}</span>' for t in ([r["zeit"]] if r["zeit"] else []) + r["tags"])
    if fehlt:
        info = f'<span class="fehlt">fehlt: {e(", ".join(name for _, name in fehlt))}</span>' + info
    grau = ' class="grau"' if fehlt else ""
    suche = e(" ".join([r["titel"], *r["tags"], *r["zutaten"]]).lower())
    return (f'<li{grau} data-suche="{suche}"><a href="/rezept?d={n}"><span class="titel">{e(r["titel"])}'
            + (' <span class="heute">Heute</span>' if n == h else "") + f'</span>{rechts}'
            + f'<span class="info">{info}</span></a></li>')


SUCH_SKRIPT = """
const suche = document.getElementById('suche');
if (suche) suche.addEventListener('input', () => {
  const q = suche.value.trim().toLowerCase();
  for (const li of document.querySelectorAll('[data-suche]')) li.hidden = !li.dataset.suche.includes(q);
  for (const g of document.querySelectorAll('.gruppe')) g.hidden = !g.querySelector('[data-suche]:not([hidden])');
});
"""


def adresse(m="", tags=(), kochbar=False):
    """Adresse der Rezeptliste mit ihren Filtern."""
    q = urlencode([("m", m)] * bool(m) + [("t", t) for t in tags] + [("k", "1")] * kochbar)
    return "/rezepte" + ("?" + q if q else "")


def liste(m="", tags=(), kochbar=False, gespeichert=""):
    """Rezeptliste. Filter stehen in der Adresse: Mahlzeit, Tags (alle muessen passen), nur kochbare.
    gespeichert: Zahl aus der Sammel-Vorschau, fuer die Meldung „3 Rezepte gespeichert“."""
    meldung = f'<p class="ok">{gespeichert} Rezepte gespeichert.</p>' if re.fullmatch(r"[0-9]{1,2}", gespeichert) else ""
    m = m if m in dict(MAHLZEITEN) else ""
    tags = list(dict.fromkeys(t.strip().lower()[:40] for t in tags if t.strip()))[:5]
    import vorrat  # erst hier, weil vorrat.py rezepte.py importiert
    h, pruefen = heute_name(), vorrat.pruefer()
    try:
        offen = len(vorrat.offene_zutaten(vorrat.laden()))
    except ValueError:  # kaputte vorrat.json: Rezepte trotzdem zeigen
        offen = 0
    zuordnen = f'<p class="erklaerung"><a href="/zuordnen">{offen} Zutaten ohne Artikel zuordnen</a></p>' if offen else ""
    rezepte = [(n, r, pruefen(r)) for n, r in alle() if not m or m in r["mahlzeit"]]
    aktuell = ' aria-current="page"'
    reiter = "".join(f'<a href="{e(adresse(k, tags, kochbar))}"{aktuell if k == m else ""}>{name}</a>'
                     for k, name in (("", "Alle"),) + MAHLZEITEN)
    # Chips: „Kochbar“ und jeder Tag, der in mindestens zwei Rezepten steht, in der Schreibweise des ersten Rezepts
    name = {}
    for _, r, _ in rezepte:
        for t in r["tags"]:
            name.setdefault(t.lower(), t)
    oft = Counter(t for _, r, _ in rezepte for t in {x.lower() for x in r["tags"]})
    an = ' aria-current="true"'
    chips = [f'<a href="{e(adresse(m, tags, not kochbar))}"{an if kochbar else ""}>Kochbar</a>'] + [
        f'<a href="{e(adresse(m, [x for x in tags if x != t] if t in tags else tags + [t], kochbar))}"{an if t in tags else ""}>'
        f'{e(name.get(t, t))}</a>'
        for t in sorted(set(tags) | {t for t, n in oft.items() if n >= 2}, key=lambda t: (-oft[t], t))]
    gezeigt = [(n, r, p) for n, r, p in rezepte if set(tags) <= {x.lower() for x in r["tags"]}
               and (not kochbar or (p["bekannt"] and not p["fehlt"]))]
    if gezeigt:
        inhalt = '<ul class="liste">' + "".join(zeile(n, r, h, p) for n, r, p in gezeigt) + "</ul>"
    elif tags or kochbar:
        inhalt = f'<p class="leer">Kein Rezept passt. <a href="{e(adresse(m))}">Filter zurücksetzen</a></p>'
    elif m:
        inhalt = (f'<p class="leer">Noch kein {dict(MAHLZEITEN)[m]}. Beim neuen Rezept „{dict(MAHLZEITEN)[m]}“ wählen '
                  'oder bei einem Rezept unter Bearbeiten die Zeile „Mahlzeit:“ ändern.</p>')
    else:
        inhalt = '<p class="leer">Noch keine Rezepte. Das erste legst du über „Neues Rezept“ an.</p>'
    filter_ = (f'<nav class="chips" aria-label="Filter">{"".join(chips)}</nav>'
               '<input type="search" id="suche" placeholder="Suchen" aria-label="Rezepte suchen">') if rezepte else ""
    return seite("Rezepte", f"""<div class="kopf"><h1>Rezepte</h1>
<p class="aktionen"><a class="knopf" href="/neu">Neues Rezept</a></p></div>
{meldung}
<nav class="reiter" aria-label="Mahlzeit">{reiter}</nav>
{filter_}
{zuordnen}
{inhalt}
<script>{SUCH_SKRIPT}</script>""")


MARKEN = {"da": "da", "wenig": "wenig da", "andere Sorte": "andere Sorte da", "fehlt": "fehlt", "egal": ""}


def zum_rezept(d, portionen=""):
    """Adresse des Rezepts; nach einem Knopf bleiben die Portionen (nur Ziffern, den Rest prueft umgerechnet())."""
    return f"/rezept?d={d}" + (f"&portionen={portionen}" if re.fullmatch(r"[0-9]{1,2}", portionen) else "")


def regler(name, r):
    """Portionen − 2 + als zwei Links; nur, wenn die Datei eine einfache Zahl hat."""
    if not re.fullmatch(r"[0-9]{1,2}", r["portionen"]):
        return ""
    n = int(r["portionen"])

    def knopf(k, zeichen, text):
        if not 1 <= k <= 12:
            return f'<button type="button" disabled aria-label="{text}">{zeichen}</button>'
        return f'<a class="knopf zweit" href="{e(zum_rezept(name, str(k)))}#zutaten" aria-label="{text}">{zeichen}</a>'
    return (f'<div class="portionen"><span>Portionen</span><span class="zaehler">{knopf(n - 1, "−", "Eine Portion weniger")}'
            f'<span class="zahl">{n}</span>{knopf(n + 1, "+", "Eine Portion mehr")}</span></div>')


def ansicht(name, portionen=""):
    import vorrat
    original = lesen(text(name))[0]
    r = umgerechnet(original, portionen)
    p = vorrat.pruefer()(original)  # der Vorrat kennt keine Mengen; Zeilen und Reihenfolge sind gleich
    jetzt = e(r["portionen"]) if "basis" in r else ""
    mit = f'<input type="hidden" name="portionen" value="{jetzt}">' if jetzt else ""
    marken = [f' <a class="marke m-offen" href="/zuordnen">zuordnen</a>' if m == "?" else
              f' <span class="marke m-{m.split()[0]}">{MARKEN[m]}</span>' if MARKEN[m] else "" for m in p["zeilen"]]
    ist_heute = heute_name() == name
    hinweis = '<p class="ok">Steht auf dem Kindle, sobald er das nächste Bild holt.</p>' if ist_heute and kindle_da() else ""
    if p["fehlt"] and p["drauf"]:
        hinweis += '<p class="ok">Was fehlt, steht auf der <a href="/einkauf">Einkaufsliste</a>.</p>'
    fehlendes = (f'<form method="post" action="/einkauf/rezept"><input type="hidden" name="d" value="{name}">{mit}'
                 f'<button class="zweit">Fehlendes auf die Liste ({len(p["fehlt"])})</button></form>') if p["fehlt"] and not p["drauf"] else ""
    return seite(r["titel"], f"""{ZURUECK}
<article class="rezept">{rezept_html(r, marken, regler(name, r))}</article>
{hinweis}
<div class="knoepfe">
<a class="knopf" href="{e(f"/kochmodus?d={name}" + (f"&portionen={r['portionen']}" if jetzt else ""))}">Kochmodus</a>
<form method="post" action="/heute"><input type="hidden" name="d" value="{name}">{mit}
<button{' class="zweit"' if ist_heute else ""} name="an" value="{0 if ist_heute else 1}">{"Nicht mehr heute" if ist_heute else "Heute kochen"}</button></form>
{fehlendes}
<a class="knopf zweit" href="/gekocht?d={name}">Gekocht</a>
<a class="knopf zweit" href="/bearbeiten?d={name}">Bearbeiten</a>
<form method="post" action="/loeschen" onsubmit="return confirm('Rezept in den Papierkorb legen?')">
<input type="hidden" name="d" value="{name}"><button class="zweit gefahr">Löschen</button></form>
</div>""")


DAUER = re.compile(r"(?<![\d,.])(\d+)(?:\s*[–-]\s*\d+)?\s*(min|minuten?|sek|sekunden?|std|stunden?)(?![a-zäöüß])\.?", re.I)


def dauern(text):
    """Schritttext als maskiertes HTML, Zeitangaben („9–10 min“, kleinere Zahl zaehlt) werden Timer-Knoepfe."""
    def knopf(m):
        einheit = m.group(2).lower()
        sek = int(m.group(1)) * (3600 if einheit.startswith("st") else 1 if einheit.startswith("se") else 60)
        return f'<button type="button" class="uhr" data-sek="{sek}">{m.group(0)}</button>'
    return DAUER.sub(knopf, e(text))


KOCHMODUS_SKRIPT = """
const abschnitte = document.querySelectorAll('.kochschritt');
const feld = document.getElementById('uhren');
const SCHLUESSEL = 'uhren:' + new URLSearchParams(location.search).get('d');
let uhren = [], audio = null, sperre = null, zuletzt = 0;
try {
  const alt = JSON.parse(sessionStorage.getItem(SCHLUESSEL) || '[]');
  if (Array.isArray(alt)) uhren = alt.filter(u => u && Number.isFinite(u.ende) && typeof u.text === 'string' && Number.isInteger(u.schritt));
} catch (f) {}
function sichern() {
  try { sessionStorage.setItem(SCHLUESSEL, JSON.stringify(uhren.map(u => ({ ende: u.ende, text: u.text, schritt: u.schritt })))); } catch (f) {}
}
// Display anlassen; ohne Wake Lock (HTTP) bleibt nur der Hinweis
async function wach() {
  if (!('wakeLock' in navigator)) { document.getElementById('wach').hidden = false; return; }
  if (sperre && !sperre.released) return;
  try { sperre = await navigator.wakeLock.request('screen'); } catch (f) {}
}
wach();
document.addEventListener('visibilitychange', () => { if (!document.hidden) wach(); });
document.addEventListener('click', wach, { once: true });
function ton() {
  if (!audio) return;
  const t = audio.currentTime;
  for (let i = 0; i < 3; i++) {
    const o = audio.createOscillator(), g = audio.createGain();
    o.frequency.value = 880; o.connect(g); g.connect(audio.destination);
    g.gain.setValueAtTime(0.3, t + i * 0.25); g.gain.setValueAtTime(0, t + i * 0.25 + 0.15);
    o.start(t + i * 0.25); o.stop(t + i * 0.25 + 0.2);
  }
}
// Zeilen nur bei neuen/beendeten Timern neu bauen, sonst trifft ein Tipp auf × ins Leere
function bauen() {
  feld.replaceChildren();
  for (const u of uhren) {
    u.zeile = document.createElement('div'); u.zeile.className = 'uhr-zeile';
    u.anzeige = document.createElement('span');
    const x = document.createElement('button');
    x.type = 'button'; x.textContent = '×'; x.setAttribute('aria-label', 'Timer beenden');
    x.addEventListener('click', () => { uhren = uhren.filter(w => w !== u); sichern(); bauen(); });
    u.zeile.append(u.anzeige, x); feld.append(u.zeile);
  }
  zeigen();
}
function zeigen() {
  const jetzt = Date.now();
  let piep = false;
  for (const u of uhren) {
    const rest = Math.max(0, Math.ceil((u.ende - jetzt) / 1000));
    if (!rest) piep = true;
    u.zeile.classList.toggle('klingelt', !rest);
    u.anzeige.textContent = 'Schritt ' + u.schritt + ' · '
      + (rest ? Math.floor(rest / 60) + ':' + String(rest % 60).padStart(2, '0') : 'fertig (' + u.text + ')');
  }
  if (piep && jetzt - zuletzt > 4000) { zuletzt = jetzt; ton(); }
}
document.addEventListener('click', ev => {
  const a = ev.target.closest('a[data-schritt]');
  if (a) {
    ev.preventDefault();
    for (const s of abschnitte) s.hidden = s.dataset.schritt !== a.dataset.schritt;
    history.replaceState(null, '', a.getAttribute('href'));
    window.scrollTo(0, 0);
    return;
  }
  const b = ev.target.closest('button.uhr');
  if (!b) return;
  try {  // iOS spielt Ton nur, wenn der AudioContext in einer Geste angelegt wurde
    const AC = window.AudioContext || window.webkitAudioContext;
    if (AC && !audio) audio = new AC();
    if (audio) audio.resume();
  } catch (f) {}
  uhren.push({ ende: Date.now() + b.dataset.sek * 1000, text: b.textContent, schritt: Number(b.closest('.kochschritt').dataset.schritt) });
  sichern(); bauen();
});
bauen();
setInterval(zeigen, 1000);
"""


def kochmodus(name, portionen, schritt):
    import vorrat
    r = umgerechnet(lesen(text(name))[0], portionen)
    n = len(r["zubereitung"])
    k = min(int(schritt), n) if re.fullmatch(r"[0-9]{1,4}", schritt) else 0
    p = r["portionen"] if "basis" in r else ""
    zum = e(zum_rezept(name, p))
    gehe = lambda i: e(f"/kochmodus?d={name}" + (f"&portionen={p}" if p else "") + f"&schritt={i}")
    hinweis = f'<p class="erklaerung">Mengen im Text gelten für {r["basis"]} Portionen.</p>' if p else ""
    je = vorrat.zutaten_je_schritt(r)

    def abschnitt(i, inhalt):
        zurueck = f'<a class="knopf zweit" href="{gehe(i - 1)}" data-schritt="{i - 1}">Zurück</a>' if i else f'<a class="knopf zweit" href="{zum}">Zurück</a>'
        vor = (f'<a class="knopf" href="{gehe(i + 1)}" data-schritt="{i + 1}">Weiter</a>' if i < n
               else f'<a class="knopf" href="/gekocht?d={name}">Fertig</a>')
        return (f'<section class="kochschritt" data-schritt="{i}"{"" if i == k else " hidden"}>{inhalt}'
                f'<nav class="kochnav" aria-label="Schritte">{zurueck}{vor}</nav></section>')
    teile = [abschnitt(0, '<h2>Bereitstellen</h2><ul class="zutaten">' + "".join(f"<li>{e(z)}</li>" for z in r["zutaten"]) + "</ul>")]
    for i, s in enumerate(r["zubereitung"], 1):
        dafuer = ('<h2>Dafür</h2><ul class="zutaten">' + "".join(f"<li>{e(r['zutaten'][j])}</li>" for j in je[i - 1]) + "</ul>") if je[i - 1] else ""
        teile.append(abschnitt(i, f'<h2>Schritt {i} von {n}</h2><p class="kochtext">{dauern(s)}</p>{hinweis}{dafuer}'))
    return seite(r["titel"], f"""<p><a class="zurueck" href="{zum}">Zurück zum Rezept</a></p>
<h1>{e(r["titel"])}</h1>
<p class="erklaerung" id="wach" hidden>Das Display bleibt nur über die https-Adresse an. Sonst in den iPhone-Einstellungen „Automatische Sperre“ auf „Nie“ stellen.</p>
<div id="uhren" class="uhren" aria-live="polite"></div>
{"".join(teile)}
<script>{KOCHMODUS_SKRIPT}</script>""", oben=None)


# --- Kindle-Browser: WebKit 531 von 2010 (User-Agent im nginx-Log, 2026-11-09). Er kennt keine CSS-Variablen, kein
# Flexbox und kein neues JavaScript, deshalb eigenes CSS und ein Skript in altem JavaScript. Groessen in em folgen
# der Schrift, die das Skript einstellt; Knoepfe haben feste Pixel und bleiben fingerbreit. Er unterstreicht jeden
# Link, auch mit text-decoration: none (Foto 2026-11-09: aus − und + wurden = und ±). Deshalb ist alles, was ein
# Knopf sein soll, ein <button>, zum Weitergehen in einem GET-Formular. ---

KINDLE_STIL = """
body { margin: 0; padding: 10px 18px 24px; background: #fff; color: #000; font-size: 26px; line-height: 1.3; }
h1 { font-size: 1.35em; line-height: 1.15; margin: .2em 0 .15em; }
h2 { font-size: .8em; text-transform: uppercase; letter-spacing: .08em; margin: .7em 0 .25em; padding-bottom: .1em;
     border-bottom: 2px solid #000; }
a { color: #000; }
p { margin: .3em 0; }
.zurueck { display: block; padding: 6px 0; font-size: .8em; }
.erklaerung { font-size: .8em; }
.kopf { overflow: hidden; }
.portionen { float: right; margin-left: 12px; }
.portionen span { vertical-align: middle; }
.portionen .zaehler { margin-left: 10px; }
.zahl { display: inline-block; min-width: 1.6em; text-align: center; font-weight: bold; }
table.zutaten { width: 100%; border-collapse: collapse; }
.zutaten td { width: 50%; vertical-align: top; padding: .12em .6em .12em 0; }
.fehlt { font-size: .7em; font-weight: bold; text-transform: uppercase; border: 2px solid #000; padding: 0 .2em; white-space: nowrap; }
.schritte { margin: 0; padding-left: 1.5em; }
.schritte li { margin-bottom: .3em; }
.knoepfe form { display: inline; }
button { display: inline-block; font-family: inherit; font-size: 24px; line-height: 1.2; padding: 14px 22px;
         margin: 10px 10px 0 0; border: 3px solid #000; background: #fff; color: #000; -webkit-appearance: none; }
button[disabled] { border-color: #999; color: #999; }
.zaehler button { padding: 8px 18px; margin: 0; }
.liste { list-style: none; margin: 0; padding: 0; }
.liste a { display: block; padding: .35em 0; border-bottom: 1px solid #000; text-decoration: none; }
.werte { font-size: .75em; white-space: nowrap; }
.artikelliste { list-style: none; margin: 0; padding: 0; }
.artikel { padding: 5px 0; border-bottom: 2px solid #000; }
.artikel button, .artikel form > .name, .artikel .zaehler { display: inline-block; vertical-align: middle; }
.artikel .stand { width: 74%; margin: 0; padding: 8px 16px; font-size: 1em; text-align: left; }
.stand .wert:before { content: " · "; }
.unter { display: block; }
.wert, .unter { font-size: .75em; }
.ist-leer .wert { font-weight: bold; }
.artikel form > .name { width: 44%; }
.artikel .zaehler { width: 30%; }
.liste-knopf { width: 22%; margin: 0 0 0 3%; padding: 8px 0; text-align: center; }
.liste-knopf[aria-pressed="true"] { background: #000; color: #fff; }
"""

KINDLE_SKRIPT = """
// Schrift so gross wie moeglich, aber alles auf einem Bildschirm: Scrollen ist auf E-Ink traege. Unter 18 px wird gescrollt.
// Der Kindle meldet als innerHeight die ganze Seite (Foto 2026-11-09: 32 px und abgeschnitten). Sichtbar sind unter
// Statuszeile und Browserleiste etwa 900 der 1024 px.
(function () {
  var b = document.body, klein = 18, gross = 32, mitte, hoehe = Math.min(window.innerHeight, 880);
  function passt(px) {
    b.style.fontSize = px + 'px';
    return b.offsetHeight <= hoehe;  // nur der Inhalt; scrollHeight der Seite ist nie kleiner als das Fenster
  }
  if (passt(gross)) return;
  while (gross - klein > 1) {
    mitte = Math.floor((klein + gross) / 2);
    if (passt(mitte)) klein = mitte; else gross = mitte;
  }
  passt(klein);
})();
"""


def kindle_seite(titel, inhalt, passend=False):
    """Ganze Seite fuer den Kindle-Browser. passend: Schrift so, dass alles auf einen Bildschirm passt (Rezept und
    Gekocht; die Liste bliebe bei 25 Rezepten auch mit 18 px zu lang, dort lieber gut lesbar und einmal wischen)."""
    return "text/html; charset=utf-8", f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{e(titel)}</title><style>{KINDLE_STIL}</style></head><body>
{inhalt}
{f"<script>{KINDLE_SKRIPT}</script>" if passend else ""}</body></html>""".encode()


def kindle_liste():
    """Alle Rezepte nach Mahlzeit wie im Rezeptbuch, mit Kurzwerten zum Auswaehlen."""
    inhalt = "".join(f"<h2>{e(gn)}</h2><ul class=\"liste\">" + "".join(
        f'<li><a href="/kindle/rezept?d={n}">{e(r["titel"])} <span class="werte">{e(kurz(r))}</span></a></li>'
        for n, r in liste) + "</ul>" for gn, liste in gruppen(alle()))
    return kindle_seite("Rezepte", "<h1>Rezepte</h1>" + (inhalt or '<p class="erklaerung">Noch keine Rezepte.</p>'))


def kindle_rezept(name, portionen=""):
    """Ein Rezept auf einem Bildschirm: Zutaten in zwei Spalten, darunter die Schritte; Fehlendes ist markiert."""
    import vorrat
    original = lesen(text(name))[0]
    r = umgerechnet(original, portionen)
    p = vorrat.pruefer()(original)  # wie ansicht(): der Vorrat kennt keine Mengen, Zeilen und Reihenfolge sind gleich
    jetzt = e(r["portionen"]) if "basis" in r else ""
    z = [e(x) + (' <span class="fehlt">fehlt</span>' if m == "fehlt" else "") for x, m in zip(r["zutaten"], p["zeilen"])]
    h = (len(z) + 1) // 2  # links die erste Haelfte, rechts der Rest: von oben nach unten gelesen
    zutaten = "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in zip(z[:h], z[h:] + [""]))
    meta = " · ".join(x for x in (r["zeit"], kurz(r)) if x)
    if re.fullmatch(r"[0-9]{1,2}", r["portionen"]):  # wie regler(), aber Knoepfe statt Links
        n = int(r["portionen"])
        pm = [f'<button name="portionen" value="{k}" aria-label="Eine Portion {t}"{"" if 1 <= k <= 12 else " disabled"}>{z}</button>'
              for k, z, t in ((n - 1, "−", "weniger"), (n + 1, "+", "mehr"))]
        knopf = (f'<form class="portionen" method="get" action="/kindle/rezept"><input type="hidden" name="d" value="{name}">'
                 f'<span>Portionen</span><span class="zaehler">{pm[0]}<span class="zahl">{n}</span>{pm[1]}</span></form>')
    else:
        knopf = f'<p>{e(r["portionen"])} Portionen</p>' if r["portionen"] else ""
    hinweis = (f'<p class="erklaerung">Umgerechnet von {r["basis"]} Portionen, Mengen im Text gelten für {r["basis"]}. '
               'Gewürze nach Geschmack anpassen.</p>') if jetzt else ""
    mit = f'<input type="hidden" name="portionen" value="{jetzt}">' if jetzt else ""
    if p["fehlt"] and not p["drauf"]:
        fehlendes = (f'<form method="post" action="/kindle/fehlendes"><input type="hidden" name="d" value="{name}">{mit}'
                     f'<button>Fehlendes auf die Liste ({len(p["fehlt"])})</button></form>')
    else:
        fehlendes = '<p class="erklaerung">Was fehlt, steht auf der Einkaufsliste.</p>' if p["fehlt"] else ""
    tipp = f'<p><b>Tipp:</b> {e(r["tipp"])}</p>' if r["tipp"] else ""
    return kindle_seite(r["titel"], f"""<a class="zurueck" href="/kindle">‹ Alle Rezepte</a>
<h1>{e(r["titel"])}</h1>
<div class="kopf">{knopf}<p>{e(meta)}</p></div>
<h2>Zutaten</h2><table class="zutaten">{zutaten}</table>{hinweis}
<h2>Zubereitung</h2><ol class="schritte">{"".join(f"<li>{e(s)}</li>" for s in r["zubereitung"])}</ol>{tipp}
<div class="knoepfe">{fehlendes}<form method="get" action="/kindle/gekocht"><input type="hidden" name="d" value="{name}">
<button>Gekocht</button></form></div>""", passend=True)


def vorlieben():
    try:
        with open(VORLIEBEN, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""


NUR_VORRAT = "Kaufe nichts dazu."
DAZUKAUFEN = "Höchstens 2 Zutaten dürfen nicht unter ZUTATEN stehen, nenne sie im Tipp."


def prompt(damit=(), zutaten=""):
    """PROMPT mit den vorhandenen Rezepten (damit nichts doppelt kommt), Vorlieben und, aus „Kochen“, der Auswahl und
    dem Vorrat als ZUTATEN; die Bloecke stehen unter ZUTATEN."""
    titel = [r["titel"] for _, r in alle()[:60]]
    bloecke = [f"VORHANDEN: {'; '.join(titel)}"] * bool(titel) + [f"VORLIEBEN:\n{v}" for v in [vorlieben()] if v]
    if damit:
        bloecke += [f"DAMIT KOCHEN: {', '.join(damit)}", "Verwende die Zutaten bei DAMIT KOCHEN.", f"EINKAUFEN: {DAZUKAUFEN}"]
    zeile = lambda m: "\n".join([f"ZUTATEN: {zutaten}" if zutaten else m.group(1), *bloecke])
    return re.sub(r"^(ZUTATEN:.*)$", zeile, PROMPT, count=1, flags=re.M)


def segment(name, werte, legende, an=None):
    return (f'<fieldset class="seg"><legend>{legende}</legend>' + "".join(
        f'<input type="radio" name="{name}" id="{name}-{i}" value="{e(wert)}"{" checked" * (wert == an)}>'
        f'<label for="{name}-{i}">{e(text)}</label>' for i, (wert, text) in enumerate(werte)) + "</fieldset>")


def neu(w=()):
    import vorrat
    damit, da, alle_artikel = vorrat.fuer_prompt(w)
    da = ", ".join(da) or "nichts"
    wahl = segment("mahlzeit", [(x, x) for x in ("Mittagessen", "Abendessen", "beides")], "Mahlzeit")
    wahl += segment("zeit", [("20 min", "bis 20 min"), ("45 min", "bis 45 min"), ("egal", "egal")], "Zeit")
    wahl += segment("portionen", [(x, x) for x in ("1", "2", "4")], "Portionen")
    wahl += segment("anzahl", [(x, x) for x in ("1", "3", "5")], "Wie viele Rezepte")
    if alle_artikel:  # vorrat.json kaputt: ohne diese Wahl
        wahl += segment("zutaten", [(da, "was da ist"), (", ".join(alle_artikel), "alle Artikel"), ("frei", "egal")],
                        "Zutaten", da if damit else None)
    if damit:
        wahl += segment("einkaufen", [(DAZUKAUFEN, "1–2 dazukaufen"), (NUR_VORRAT, "nichts kaufen")], "Einkaufen",
                        DAZUKAUFEN)
    v = vorlieben()
    v_text = (f'<p class="erklaerung">Eure Vorlieben stehen im Prompt. <a href="/vorlieben">Ändern</a></p>' if v else
              '<p class="erklaerung"><a href="/vorlieben">Vorlieben hinterlegen</a>: Sie stehen dann in jedem Prompt.</p>')
    wunsch = f' value="{e("etwas mit " + ", ".join(damit))}"' if damit else ""
    return seite("Neues Rezept", f"""{ZURUECK}
<h1>Neues Rezept</h1>
<section class="schritt"><h2>1. Prompt kopieren</h2>
<label for="wunsch">Was soll es geben?</label>
<input id="wunsch" placeholder="z. B. schnelle Pasta für 2, Zucchini muss weg"{wunsch}>
{wahl}
{v_text}
<p class="aktionen"><button type="button" onclick="kopieren()">Prompt kopieren</button> <span id="status" role="status"></span></p>
<p class="erklaerung">Dann Claude oder ChatGPT öffnen, einfügen, abschicken und die Antwort kopieren.
Ein fertiges Rezept (Text, Foto) kannst du mitschicken, dann wird es umgewandelt.</p>
<details><summary>Prompt ansehen</summary><textarea id="prompt" rows="12" readonly>{e(prompt(damit, da if damit else ""))}</textarea></details></section>
<section class="schritt"><h2>2. Antwort einfügen</h2>
<form method="post" action="/vorschau">
<textarea name="text" rows="12" aria-label="Antwort von Claude oder ChatGPT" placeholder="Antwort hier einfügen"></textarea>
<button class="zweit">Vorschau</button></form></section>
<script>{SKRIPT}</script>""")


def vorlieben_seite():
    return seite("Vorlieben", f"""<p><a class="zurueck" href="/neu">Neues Rezept</a></p>
<h1>Unsere Vorlieben</h1>
<p class="erklaerung">Steht in jedem Prompt für ein neues Rezept. Freitext, die KI versteht das.</p>
<form method="post" action="/vorlieben">
<textarea name="text" rows="10" maxlength="2000" aria-label="Unsere Vorlieben" placeholder="{e(BEISPIEL)}">{e(vorlieben())}</textarea>
<button>Speichern</button></form>""", "/rezepte")


def vorschau(roh, name=""):
    """Formatpruefung, Vorschau und Textfeld; dient auch als Bearbeiten-Seite."""
    inhalt = saeubern(roh)
    r, fehler, hinweise = lesen(inhalt)
    pruefung = ("".join(f'<p class="fehler">{e(f)}</p>' for f in fehler) or '<p class="ok">Format passt.</p>') \
        + "".join(f'<p class="hinweis">{e(h)}</p>' for h in hinweise)
    return seite("Vorschau", f"""{ZURUECK}
<h1>{"Bearbeiten" if name else "Vorschau"}</h1>
<form method="post" action="/speichern"><input type="hidden" name="d" value="{e(name)}">
{pruefung}
<p class="aktionen"><button{" disabled" if fehler else ""}>Speichern</button></p>
<div class="vorschau rezept">{rezept_html(r)}</div>
<h2>Text</h2>
<textarea name="text" rows="16" aria-label="Rezepttext">{e(inhalt)}</textarea>
<button class="zweit" formaction="/vorschau">Vorschau aktualisieren</button>
</form>""")


def vorschau_mehrere(teile):
    """Sammel-Vorschau fuer eine Antwort mit mehreren Rezepten: je Rezept die Formatpruefung und ein Haken. Der Haken
    traegt den Rezepttext als Wert, /speichern bekommt so nur die gewaehlten. Rezepte mit Fehlern sind nicht waehlbar."""
    karten = []
    for i, inhalt in enumerate(teile):
        r, fehler, hinweise = lesen(inhalt)
        pruefung = "".join(f'<p class="fehler">{e(f)}</p>' for f in fehler) + "".join(f'<p class="hinweis">{e(h)}</p>' for h in hinweise)
        karten.append(f'<section class="schritt"><p class="feld-haken"><input type="checkbox" name="text" id="t-{i}" value="{e(inhalt)}"'
                      f'{" disabled" if fehler else " checked"}><label for="t-{i}">{e(r["titel"] or "Ohne Titel")}</label></p>'
                      f'{pruefung}<details><summary>Ansehen</summary><div class="vorschau rezept">{rezept_html(r)}</div></details></section>')
    return seite("Vorschau", f"""{ZURUECK}
<h1>{len(teile)} Rezepte</h1>
<p class="erklaerung">Gespeichert wird, was einen Haken hat. Ändern geht danach im Rezept unter „Bearbeiten“.</p>
<form method="post" action="/speichern">{"".join(karten)}
<div class="knoepfe"><button>Ausgewählte speichern</button></div></form>""")


def xhtml(titel, body):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" xml:lang="de" lang="de">
<head><title>{e(titel)}</title></head>
<body>
{body}
</body></html>"""


def gruppen(rezepte):
    """Fuers Rezeptbuch: [(Name, [(name, rezept)])] nach Mahlzeit; „beides“ steht in beiden Gruppen."""
    g = [(n, [x for x in rezepte if m in x[1]["mahlzeit"]]) for m, n in MAHLZEITEN]
    g.append(("Weitere", [x for x in rezepte if not x[1]["mahlzeit"]]))
    return [(n, liste) for n, liste in g if liste]


def epub():
    """Alle Rezepte als EPUB 3; das Inhaltsverzeichnis ist zugleich die erste Seite, toc.ncx fuer aeltere Leser.
    Eintraege mit Naehrwerten im Titel, nach Mahlzeit gruppiert."""
    rezepte = alle()
    uid = "urn:kuechendash:rezeptbuch"
    g = gruppen(rezepte)
    reihe = {"inhalt.xhtml": 1, **{f"r-{n}.xhtml": i for i, (n, _) in enumerate(rezepte, 2)}}  # playOrder je Ziel

    def label(r):
        return f"{r['titel']} ({kurz(r)})" if kurz(r) else r["titel"]

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")  # muss zuerst und unkomprimiert kommen
        z.writestr("META-INF/container.xml", '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile '
                   'full-path="OEBPS/buch.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        z.writestr("OEBPS/inhalt.xhtml", xhtml("Inhalt", '<nav epub:type="toc" id="toc"><h1>Rezepte</h1><ol>' + "".join(
            f'<li id="g{i}"><span>{e(gn)}</span><ol>'
            + "".join(f'<li><a href="r-{n}.xhtml">{e(label(r))}</a></li>' for n, r in liste) + "</ol></li>"
            for i, (gn, liste) in enumerate(g)) + "</ol></nav>"))
        for n, r in rezepte:
            z.writestr(f"OEBPS/r-{n}.xhtml", xhtml(r["titel"], rezept_html(r) + '<p><a href="inhalt.xhtml">Inhalt</a></p>'))
        z.writestr("OEBPS/toc.ncx", f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1"><head><meta name="dtb:uid" content="{uid}"/></head>
<docTitle><text>Rezeptbuch</text></docTitle><navMap>"""
                   + '<navPoint id="inhalt" playOrder="1"><navLabel><text>Inhalt</text></navLabel><content src="inhalt.xhtml"/></navPoint>'
                   + "".join(f'<navPoint id="g{i}" playOrder="1"><navLabel><text>{e(gn)}</text></navLabel>'
                             f'<content src="inhalt.xhtml#g{i}"/>'
                             + "".join(f'<navPoint id="g{i}-{n}" playOrder="{reihe[f"r-{n}.xhtml"]}"><navLabel>'
                                       f'<text>{e(label(r))}</text></navLabel><content src="r-{n}.xhtml"/></navPoint>'
                                       for n, r in liste) + "</navPoint>"
                             for i, (gn, liste) in enumerate(g))
                   + "</navMap></ncx>")
        z.writestr("OEBPS/buch.opf", f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid" xml:lang="de">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="uid">{uid}</dc:identifier>
<dc:title>Rezeptbuch</dc:title><dc:language>de</dc:language>
<meta property="dcterms:modified">{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}</meta></metadata>
<manifest><item id="inhalt" href="inhalt.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>"""
                   + "".join(f'<item id="r-{n}" href="r-{n}.xhtml" media-type="application/xhtml+xml"/>' for n, _ in rezepte)
                   + '</manifest><spine toc="ncx"><itemref idref="inhalt"/>'
                   + "".join(f'<itemref idref="r-{n}"/>' for n, _ in rezepte) + "</spine></package>")
    return buf.getvalue()


def get(weg, q):
    d = q.get("d", [""])[0]
    if weg == "/":
        import vorrat
        return vorrat.start_seite()
    if weg == "/rezepte":
        return liste(q.get("m", [""])[0], q.get("t", []), q.get("k", [""])[0] == "1", q.get("gespeichert", [""])[0])
    if weg == "/neu":
        return neu(q.get("w", []))
    if weg == "/vorlieben":
        return vorlieben_seite()
    if weg == "/rezept":
        return ansicht(d, q.get("portionen", [""])[0])
    if weg == "/kochmodus":
        return kochmodus(d, q.get("portionen", [""])[0], q.get("schritt", [""])[0])
    if weg == "/bearbeiten":
        return vorschau(text(d), d)
    if weg == "/rezeptbuch.epub":
        return "application/epub+zip", epub()
    if weg == "/kindle":
        return kindle_liste()
    if weg == "/kindle/rezept":
        return kindle_rezept(d, q.get("portionen", [""])[0])
    if weg == "/kindle/gekocht":
        import vorrat
        return vorrat.kindle_gekocht(d)
    if weg.startswith(("/vorrat", "/einkauf", "/artikel", "/zuordnen", "/kochen", "/gekocht")):
        import vorrat  # erst hier, weil vorrat.py rezepte.py importiert
        return vorrat.get(weg, q)
    raise FileNotFoundError(weg)


def post(weg, form):
    d = form.get("d", [""])[0]
    if weg == "/vorschau":
        roh = form.get("text", [""])[0]
        teile = [roh] if d else teilen(roh)  # Bearbeiten (d) bleibt immer ein Rezept
        return vorschau_mehrere(teile) if len(teile) > 1 else vorschau(teile[0], d)
    if weg == "/speichern":
        texte = [saeubern(t) for t in form.get("text", [""])[:10]]
        if len(texte) > 1:  # aus der Sammel-Vorschau: jedes gueltige als neues Rezept
            gut = [t for t in texte if not lesen(t)[1]]
            for t in gut:
                speichern("", t)
            return weiter(f"/rezepte?gespeichert={len(gut)}")
        inhalt = texte[0]
        if lesen(inhalt)[1]:
            return vorschau(inhalt, d)
        return weiter(f"/rezept?d={speichern(d, inhalt)}")
    if weg == "/heute":
        heute_setzen(d, form.get("an", [""])[0] == "1")
        return weiter(zum_rezept(d, form.get("portionen", [""])[0]))
    if weg == "/loeschen":
        loeschen(d)
        return weiter("/rezepte")
    if weg == "/vorlieben":
        os.makedirs(DATEN, exist_ok=True)
        schreiben(VORLIEBEN, form.get("text", [""])[0].strip()[:2000] + "\n")
        return weiter("/neu")
    if weg == "/kindle/fehlendes":  # dieselbe Logik wie am Handy, dann zurueck auf die Kindle-Seite
        import vorrat
        vorrat.post("/einkauf/rezept", form)  # prueft d
        return weiter("/kindle" + zum_rezept(d, form.get("portionen", [""])[0]))
    if weg == "/kindle/gekocht":
        import vorrat
        pfad(d)  # nur gueltige Namen in die Weiterleitung, und vor dem Speichern
        vorrat.post("/vorrat/setzen", form)  # prueft id
        return weiter(f"/kindle/gekocht?d={d}#a-{form['id'][0]}")
    if weg.startswith(("/vorrat/", "/einkauf/", "/artikel/", "/zuordnen/")):
        import vorrat
        return vorrat.post(weg, form)
    raise FileNotFoundError(weg)
