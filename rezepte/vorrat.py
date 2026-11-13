"""Vorrat und Einkaufsliste: ein Katalog aller Artikel in DATEN/vorrat.json, ohne eigenen Login (wie rezepte.py).

GET  /vorrat?f=da|fehlt&bearbeiten=1  Inventur: ein Tipp schaltet da -> wenig -> leer, Stueck-Artikel mit - und +
GET  /einkauf                         was ausgeht, was von Hand drauf ist, einmalige Eintraege
GET  /artikel?id=ID                   Artikel bearbeiten (ohne id: neuer Artikel, ?name= fuellt den Namen vor)
GET  /zuordnen                        Zutaten der Rezepte, die keinem Artikel zugeordnet sind
GET  /kochen?w=ID&w=ID                was da ist zum Auswaehlen, darunter die passenden Rezepte (teil=1: nur die)
GET  /gekocht?d=REZEPT                nach dem Kochen: die Zutaten des Rezepts mit den Knoepfen aus dem Vorrat
GET  /einkauf.json                    die Einkaufsliste nur zum Lesen (Home Assistant), einkaufsliste() fuers Kindle-Bild
POST /vorrat/setzen, /einkauf/abhaken, /einkauf/weg, /einkauf/menge, /einkauf/dazu (text oder id), /einkauf/rezept,
     /artikel/speichern, /artikel/loeschen, /zuordnen/zuordnen, /zuordnen/egal
start_seite() ist die Startseite „/“, pruefer() prueft Rezepte gegen den Vorrat (fuer rezepte.py),
kindle_gekocht() ist „Gekocht“ fuer den Kindle-Browser (/kindle/gekocht, Wege in rezepte.py).

Jeder Tipp schickt den neuen Wert, nie „umschalten“: doppelt oder wiederholt gesendet ist harmlos.
Mit teil=1 (vom Skript) kommt ein HTML-Stueck zurueck statt einer Weiterleitung.
Fehlt vorrat.json, entsteht der Katalog aus katalog-start.txt. Eine kaputte Datei wird nie ueberschrieben.
"""
import json
import os
import re
import threading
from urllib.parse import quote

import rezepte
from rezepte import e, seite, weiter

DATEI = os.path.join(rezepte.DATEN, "vorrat.json")
START = os.path.join(rezepte.HIER, "katalog-start.txt")
BEREICHE = ("Obst & Gemüse", "Kühlschrank", "Tiefkühl", "Brot", "Vorratsschrank", "Gewürze & Öle", "Haushalt", "Drogerie")
NAECHST = {"da": "wenig", "wenig": "leer", "leer": "da"}
LISTE = {"auto": "auto", "hand": "hand", "nein": ""}  # im Formular „nein“, weil parse_qs leere Werte verwirft
MENGEN = (1, 2, 4, 6, 10)
SPERRE = threading.Lock()  # der Server bedient mehrere Anfragen gleichzeitig
NICHT_ESSBAR = ("Haushalt", "Drogerie")  # nur Vorrat und Einkaufsliste, nie Rezepte
EINHEITEN = (r"(?:g|kg|ml|l|el|tl|stück|stk|prisen?|bund|dosen?|flaschen?|packungen?|pck|scheiben?|zehen?|handvoll"
             r"|bechers?|gläser|glas|etwas|ca)")
RANG = ("da", "wenig", "andere Sorte", "fehlt")  # die schlechteste Angabe gilt fuer die ganze Zeile


def neu_artikel(name, ober, bereich, stueck=False, mindestens=1, auch=(), basis=False):
    return {"name": name, "ober": ober, "bereich": bereich, "stueck": stueck, "mindestens": mindestens,
            "stand": "leer", "anzahl": 0, "auch": list(auch), "basis": basis, "liste": ""}


def kennung(a):
    return rezepte.name_aus(f"{a['ober']} {a['name']}")


def start_lesen(text):
    """katalog-start.txt -> {id: artikel}. Der obere Teil jedes Bereichs ist da, alles unter „# ergänzt“ leer."""
    artikel, bereich, ergaenzt = {}, None, False
    for zeile in text.splitlines():
        s = zeile.strip()
        if s.startswith("## "):
            bereich, ergaenzt = s[3:].strip(), False
            if bereich not in BEREICHE:
                raise ValueError(f"Unbekannter Bereich: {bereich}")
        elif s.startswith("#"):
            ergaenzt = ergaenzt or s.lstrip("# ").startswith("ergänzt")
        elif s:
            if bereich is None:
                raise ValueError(f"Artikel vor dem ersten Bereich: {s}")
            kopf, _, zusatz = s.partition("|")
            schalter, _, auch = zusatz.partition("auch:")
            schalter = [x.strip().lower() for x in schalter.split(",") if x.strip()]
            ober, _, sorten = kopf.partition(":")
            namen = [x.strip() for x in sorten.split(",") if x.strip()] or [ober.strip()]
            ober = ober.strip() if sorten.strip() else ""
            mindestens = next((int(x.split()[1]) for x in schalter if x.startswith("mindestens")), 1)
            for name in namen:
                a = neu_artikel(name, ober, bereich, "stück" in schalter, mindestens,
                                [x.strip() for x in auch.split(",") if x.strip()], "basis" in schalter)
                if not ergaenzt:
                    a["stand"], a["anzahl"] = "da", mindestens
                if kennung(a) in artikel:
                    raise ValueError(f"Doppelt: {s}")
                artikel[kennung(a)] = a
    return artikel


def laden():
    try:
        with open(DATEI, encoding="utf-8") as f:
            return json.load(f)  # kaputt: Fehler 500, die Datei bleibt, wie sie ist
    except FileNotFoundError:
        with open(START, encoding="utf-8") as f:
            return {"artikel": start_lesen(f.read()), "einmalig": []}


def speichern(v):
    os.makedirs(rezepte.DATEN, exist_ok=True)
    rezepte.schreiben(DATEI, json.dumps(v, ensure_ascii=False, indent=1))


def stand(a):
    if not a["stueck"]:
        return a["stand"]
    return "leer" if a["anzahl"] <= 0 else "wenig" if a["anzahl"] < a["mindestens"] else "da"


def voll_name(a):
    return f"{a['ober']} ({a['name']})" if a["ober"] else a["name"]


def grund(a):
    s = stand(a)
    text = f"{a['anzahl']} da, mindestens {a['mindestens']}" if s == "wenig" and a["stueck"] else \
        {"da": "", "wenig": "wenig da", "leer": "leer"}[s]
    return ", ".join(x for x in (text, a.get("fuer") and f"für {a['fuer']}") if x)


def setzen(a, neu_stand=None, anzahl=None, liste=None):
    """Was ausgeht, kommt auf die Liste; was wieder da ist, geht runter, wenn es von selbst drauf kam."""
    vorher = stand(a) != "da"
    if neu_stand in NAECHST:
        a["stand"] = neu_stand
    if anzahl is not None:
        a["anzahl"] = min(anzahl, 99)
    knapp = stand(a) != "da"
    if liste is not None:
        a["liste"] = liste
        if not liste:
            a.pop("fuer", None)
    elif knapp and not vorher and not a["liste"]:
        a["liste"] = "auto"
    elif not knapp and a["liste"] == "auto":
        a["liste"] = ""


def gruppiert(artikel):
    """[(bereich, [(id, artikel)])] in der Reihenfolge von BEREICHE, Sorten beieinander; leere Bereiche fehlen."""
    def ordnung(x):
        return rezepte.name_aus(x[1]["ober"] or x[1]["name"]), rezepte.name_aus(x[1]["name"])
    g = [(b, sorted(((i, a) for i, a in artikel.items() if a["bereich"] == b), key=ordnung)) for b in BEREICHE]
    return [(b, liste) for b, liste in g if liste]


def wert(form, k):
    return form.get(k, [""])[0]


def zahl(form, k):
    s = wert(form, k)
    return int(s) if re.fullmatch(r"[0-9]{1,4}", s) else None  # isdigit() liesse auch „²“ und 5000 Ziffern durch


def feld(k, v):
    return f'<input type="hidden" name="{k}" value="{e(str(v))}">'


def artikel(v, i):
    if i not in v["artikel"]:
        raise FileNotFoundError(i)
    return v["artikel"][i]


def suche(a):
    return e(" ".join([voll_name(a)] + a["auch"]).lower())


# --- Rezepte und Vorrat ---

def kern(zeile):
    """„0,5 Bund Petersilie (frisch), gehackt“ -> „Petersilie“: ohne Menge, Einheit, Klammer und Zusatz nach Komma."""
    zeile = zeile[:200]  # die Klammersuche waechst mit dem Quadrat der Laenge: 200.000 „(“ brauchten 16 s
    s = re.sub(rf"^\s*(?:[\d.,/½¼¾–-]+\s*)*(?:{EINHEITEN}\b\.?\s*)*", "", re.sub(r"\([^)]*\)", "", zeile), flags=re.I)
    return " ".join(s.split(",")[0].split()) or zeile.strip()  # erst die Menge weg, sonst trennt „0,5“ am Komma


def woerter(artikel):
    """[(wort, art, schluessel)], laengste zuerst. art: „ober“ (Oberbegriff), „sorte“ (Name einer Sorte, gilt nur,
    wenn der Oberbegriff auch in der Zeile steht) oder „artikel“ (Name oder Synonym)."""
    w = set()
    for i, a in artikel.items():
        if a["bereich"] in NICHT_ESSBAR:
            continue
        if a["ober"]:
            w |= {(a["ober"].lower(), "ober", a["ober"]), (a["name"].lower(), "sorte", i)}
        else:
            w.add((a["name"].lower(), "artikel", i))
        w |= {(x.lower(), "artikel", i) for x in a["auch"]}
    return sorted(w, key=lambda x: (-len(x[0]), x[1] != "sorte", x[2]))


def bedarf(zeile, artikel, w):
    """Zutatenzeile -> [(ids, bevorzugt)]. Jede Sorte in ids reicht; bevorzugt ist die Sorte, die im Rezept steht.
    Der laengste Treffer gewinnt und verbraucht seinen Text: „Süßkartoffeln“ ist nicht auch Kartoffeln."""
    zeile = rest = zeile.lower()
    gefunden = {}
    for wort, art, k in w:
        if wort not in rest or (art == "sorte" and artikel[k]["ober"].lower() not in zeile):
            continue
        if art == "ober":
            gefunden.setdefault(("ober", k), None)
        elif artikel[k]["ober"]:
            gefunden[("ober", artikel[k]["ober"])] = k
        else:
            gefunden[("id", k)] = k
        rest = rest.replace(wort, " ")
    return [(tuple(i for i, a in artikel.items() if a["ober"] == k) if art == "ober" else (k,), bev)
            for (art, k), bev in gefunden.items()]


def verfuegbar(a):
    return a["basis"] or stand(a) != "leer"


def pruefung(r, v, w):
    """Rezept gegen den Vorrat: {"zeilen": Angabe je Zutat, "fehlt": [(id, Anzeige)], "bekannt": erkannte Zutaten}.
    Angaben: da, wenig, andere Sorte, fehlt, ? (nicht zugeordnet), egal. Nicht Zugeordnetes zaehlt nicht mit."""
    artikel, egal = v["artikel"], v.get("egal", [])
    zeilen, fehlt, bekannt, nutzt = [], {}, 0, set()
    for z in r["zutaten"]:
        if kern(z).lower() in egal:
            zeilen.append("egal")
            continue
        noetig = bedarf(z, artikel, w)
        if not noetig:
            zeilen.append("?")
            continue
        bekannt += 1
        schlimmste = "da"
        for ids, bev in noetig:
            nutzt.update(ids)
            da = [i for i in ids if verfuegbar(artikel[i])]
            if not da:
                k = bev or ids[0]
                fehlt[k] = voll_name(artikel[k]) if bev or len(ids) == 1 else artikel[k]["ober"]
                angabe = "fehlt"
            elif bev and bev not in da:
                angabe = "andere Sorte"
            else:
                angabe = "da" if any(artikel[i]["basis"] or stand(artikel[i]) == "da" for i in da) else "wenig"
            schlimmste = max(schlimmste, angabe, key=RANG.index)
        zeilen.append(schlimmste)
    return {"zeilen": zeilen, "fehlt": list(fehlt.items()), "bekannt": bekannt, "nutzt": nutzt,
            "drauf": all(artikel[k]["liste"] for k in fehlt)}


def pruefer():
    """Rezept -> pruefung(), mit einmal geladenem Vorrat; fuer Listen vieler Rezepte.
    Ist vorrat.json kaputt, bleiben die Rezepte lesbar, nur ohne Abgleich."""
    try:
        v = laden()
    except ValueError as f:
        print("vorrat.json kaputt, Rezepte ohne Abgleich:", repr(f), flush=True)
        return lambda r: {"zeilen": ["egal"] * len(r["zutaten"]), "fehlt": [], "bekannt": 0, "nutzt": set(), "drauf": True}
    w = woerter(v["artikel"])
    return lambda r: pruefung(r, v, w)


def zutaten_je_schritt(r):
    """Je Zubereitungsschritt die Indizes der Zutaten, die darin vorkommen: gleicher Artikel (Zeile und Schritt) oder
    der Name der Zutat im Text. Ist vorrat.json kaputt, gilt nur der Name."""
    try:
        artikel = laden()["artikel"]
        w = woerter(artikel)
    except ValueError:
        artikel = w = None

    def ids(t):
        return {i for g, _ in bedarf(t, artikel, w) for i in g} if w is not None else set()
    # ganzes Wort (auch Mehrzahl), sonst steckt „Ei“ in „beiseite“
    zeilen = [(ids(z), re.compile(rf"\b{re.escape(kern(z))}(?:n|en|e|er|s)?\b", re.I)) for z in r["zutaten"]]
    return [[i for i, (zi, name) in enumerate(zeilen) if zi & si or name.search(s)]
            for s in r["zubereitung"] for si in [ids(s)]]


def offene_zutaten(v):
    """{Kern: [Rezepttitel]} aller Zutaten, die keinem Artikel zugeordnet und nicht „egal“ sind."""
    w, offen = woerter(v["artikel"]), {}
    for _, r in rezepte.alle():
        for z in r["zutaten"]:
            k = kern(z)
            if k.lower() not in v.get("egal", []) and not bedarf(z, v["artikel"], w):
                offen.setdefault(k, []).append(r["titel"])
    return dict(sorted(offen.items(), key=lambda x: x[0].lower()))


def zuordnen_seite():
    v = laden()
    offen = offene_zutaten(v)
    katalog = "".join(f'<option value="{e(voll_name(a))}">' for _, a in sorted(v["artikel"].items())
                      if a["bereich"] not in NICHT_ESSBAR)
    zeilen = "".join(
        f'<li class="offen"><p class="titel">{e(k)}</p><p class="tag">in {e(", ".join(dict.fromkeys(titel)))}</p>'
        f'<form class="zuordnen" method="post" action="/zuordnen/zuordnen">{feld("kern", k)}'
        f'<input name="text" list="katalog" required maxlength="60" placeholder="Artikel" aria-label="Artikel für {e(k)}">'
        f'<button>Zuordnen</button></form><div class="aktionen">'
        f'<a class="knopf zweit" href="/artikel?name={e(quote(k))}&kern={e(quote(k))}&zurueck=zuordnen">Neuer Artikel</a>'
        f'<form method="post" action="/zuordnen/egal">{feld("kern", k)}<button class="zweit">Egal</button></form></div></li>'
        for k, titel in offen.items())
    return seite("Zuordnen", f"""<p><a class="zurueck" href="/rezepte">Alle Rezepte</a></p>
<h1>Zuordnen</h1>
<p class="erklaerung">Diese Zutaten findet die Seite in keinem Artikel. Einmal zuordnen gilt für alle Rezepte.
„Egal“ heißt: zählt nie, z. B. Wasser.</p>
<datalist id="katalog">{katalog}</datalist>
{f'<ul class="artikelliste">{zeilen}</ul>' if zeilen else '<p class="ok">Alle Zutaten sind zugeordnet.</p>'}""")


def zum_kochen(artikel):
    """Essbares, das da ist, ohne Basis (Salz und Pfeffer setzt jedes Rezept voraus)."""
    return {i: a for i, a in artikel.items() if a["bereich"] not in NICHT_ESSBAR and verfuegbar(a) and not a["basis"]}


def fuer_prompt(ids):
    """Fuer den Prompt als Namen: (Auswahl aus „Kochen“, was da ist, alle essbaren Artikel). Ohne Basis, Salz und
    Pfeffer setzt der Prompt voraus."""
    try:
        artikel = laden()["artikel"]
    except ValueError:
        return [], [], []
    da = zum_kochen(artikel)
    alle = [a for a in artikel.values() if a["bereich"] not in NICHT_ESSBAR and not a["basis"]]
    namen = lambda liste: sorted((voll_name(a) for a in liste), key=rezepte.name_aus)
    return [voll_name(da[i]) for i in dict.fromkeys(ids) if i in da], namen(da.values()), namen(alle)


def kochen_treffer(v, ids):
    """Rezepte, in denen alles Ausgewaehlte vorkommt („das muss alles weg“), kochbare zuerst; dazu die Leiste unten.
    Steht unter den Kacheln, damit beim Tippen nichts verrutscht."""
    if not ids:
        return ""
    w, h, auswahl = woerter(v["artikel"]), rezepte.heute_name(), set(ids)
    treffer = sorted((len(p["fehlt"]), rezepte.name_aus(r["titel"]), n, r, p) for n, r in rezepte.alle()
                     if auswahl <= (p := pruefung(r, v, w))["nutzt"])
    neu = "/neu?" + "&".join(f"w={i}" for i in ids)
    if treffer:
        inhalt = '<ul class="liste">' + "".join(rezepte.zeile(n, r, h, p) for *_, n, r, p in treffer) + "</ul>"
        anzahl = f"{len(treffer)} Rezepte mit allem davon" if len(treffer) != 1 else "1 Rezept mit allem davon"
    else:
        inhalt = '<p class="leer">Kein eigenes Rezept enthält alles davon. „Neues Rezept daraus“ lässt eins schreiben.</p>'
        anzahl = "kein Rezept mit allem davon"
    ansehen = '<a class="knopf" href="#treffer">Ansehen</a>' if treffer else ""
    return inhalt + (f'<div class="leiste kochen-leiste"><p><b>{len(ids)} ausgewählt</b>, {anzahl}</p>'
                     f'{ansehen}<a class="knopf" href="{e(neu)}">Neues Rezept daraus</a></div>')


def kochen_seite(ids, teil=False):
    v = laden()
    da = zum_kochen(v["artikel"])
    ids = [i for i in dict.fromkeys(ids) if i in da]
    treffer = kochen_treffer(v, ids)
    if teil:
        return "text/html; charset=utf-8", treffer.encode()
    gruppen = "".join(
        f'<section class="gruppe"><h2>{e(b)}</h2><div class="chips">' + "".join(
            f'<input type="checkbox" name="w" value="{i}" id="w-{i}"{" checked" if i in ids else ""}>'
            f'<label for="w-{i}">{e(voll_name(a))}</label>' for i, a in liste) + "</div></section>"
        for b, liste in gruppiert(da))
    return seite("Kochen", f"""<div class="kopf"><h1>Kochen</h1></div>
<p class="erklaerung">Womit willst du kochen? Hier steht alles, was da ist. Die passenden Rezepte stehen darunter.</p>
<form id="auswahl" method="get" action="/kochen">{gruppen or '<p class="leer">Im Vorrat ist nichts da.</p>'}
<p class="aktionen" id="zeigen"><button>Rezepte zeigen</button></p></form>
<div id="treffer">{treffer}</div>
<script>{KOCHEN_SKRIPT}</script>""", "/kochen")


def gekocht_artikel(r):
    """Die Artikel eines Rezepts fuer „Gekocht“ (ohne Basis), in Rezeptreihenfolge: {id: artikel}."""
    v = laden()
    artikel, w, ids = v["artikel"], woerter(v["artikel"]), {}
    for z in r["zutaten"]:
        for gruppe, bev in bedarf(z, artikel, w):
            da = [i for i in gruppe if verfuegbar(artikel[i])]
            k = bev if bev in da else (da or [bev or gruppe[0]])[0]
            if not artikel[k]["basis"]:
                ids[k] = artikel[k]
    return ids


def gekocht_seite(d):
    """Nach dem Kochen: die Artikel des Rezepts mit den Knoepfen aus dem Vorrat."""
    r = rezepte.lesen(rezepte.text(d))[0]
    zeilen = "".join(zeile(i, a) for i, a in gekocht_artikel(r).items())
    return seite("Gekocht", f"""<p><a class="zurueck" href="/rezept?d={d}">{e(r["titel"])}</a></p>
<h1>Gekocht</h1>
<p class="erklaerung">Was ist jetzt wenig oder leer? Ein Tipp schaltet weiter: da, wenig, leer.
Was ausgeht, kommt auf die Einkaufsliste.</p>
{f'<ul class="artikelliste">{zeilen}</ul>' if zeilen else '<p class="leer">Keine Zutat dieses Rezepts ist einem Artikel zugeordnet.</p>'}
<div class="knoepfe"><a class="knopf" href="/rezept?d={d}">Fertig</a></div>
<div id="platz" aria-live="polite"></div>
<script>{SKRIPT}</script>""", "/rezepte")


def kindle_gekocht(d):
    """„Gekocht“ fuer den Kindle-Browser: dieselben Knoepfe ohne Skript, jeder Tipp laedt die Seite neu."""
    r = rezepte.lesen(rezepte.text(d))[0]
    zeilen = "".join(zeile(i, a, "/kindle/gekocht", feld("d", d)) for i, a in gekocht_artikel(r).items())
    return rezepte.kindle_seite("Gekocht", f"""<a class="zurueck" href="/kindle/rezept?d={d}">‹ {e(r["titel"])}</a>
<h1>Gekocht</h1>
<p class="erklaerung">Was ist jetzt wenig oder leer? Ein Tipp schaltet weiter: da, wenig, leer.
Was ausgeht, kommt auf die Einkaufsliste.</p>
{f'<ul class="artikelliste">{zeilen}</ul>' if zeilen else '<p class="erklaerung">Keine Zutat dieses Rezepts ist einem Artikel zugeordnet.</p>'}
<form method="get" action="/kindle/rezept"><input type="hidden" name="d" value="{d}"><button>Fertig</button></form>""",
                               passend=True)


def start_seite():
    """Startseite: Heute kochen, Einkaufsliste, was jetzt kochbar ist."""
    pruefen, h, alle = pruefer(), rezepte.heute_name(), rezepte.alle()
    p = {n: pruefen(r) for n, r in alle}
    kochbar = [x for x in alle if p[x[0]]["bekannt"] and not p[x[0]]["fehlt"]]
    fast = [x for x in alle if p[x[0]]["bekannt"] and len(p[x[0]]["fehlt"]) == 1]
    try:
        anzahl = len(einkaufsliste())
    except ValueError:  # kaputte vorrat.json: die Startseite trotzdem zeigen, wie /rezepte
        anzahl = None
    einkauf = ("Einkaufsliste nicht lesbar" if anzahl is None else
               "1 Sache auf der Liste" if anzahl == 1 else f"{anzahl} Sachen auf der Liste")

    def liste(rs, leer):
        return f'<ul class="liste">{"".join(rezepte.zeile(n, r, h, p[n]) for n, r in rs)}</ul>' if rs else f'<p class="leer">{leer}</p>'
    heute = [(n, r) for n, r in alle if n == h]
    return seite("Küche", f"""<div class="kopf"><h1>Küche</h1><p class="aktionen"><a class="knopf" href="/neu">Neues Rezept</a></p></div>
<h2>Heute kochen</h2>
{liste(heute, "Noch nichts markiert. Im Rezept „Heute kochen“ tippen.")}
<h2>Einkauf</h2>
<p class="einkauf-kurz"><a href="/einkauf">{einkauf}</a></p>
<h2>Jetzt kochbar</h2>
{liste(kochbar, "Für kein Rezept ist alles da.")}
<h2>Fast kochbar</h2>
{liste(fast, "Kein Rezept, bei dem nur eine Sache fehlt.")}""", "/")


# --- Vorrat ---

def zeile(i, a, weg="/vorrat/setzen", mit=""):
    """Eine Zeile der Inventur; ein Formular, der gedrueckte Knopf traegt den neuen Wert.
    weg und mit (versteckte Felder): fuer den Kindle, der danach auf seine Seite zurueck soll."""
    s, drauf = stand(a), bool(a["liste"])
    name = f'<span class="name">{e(a["name"])}</span>'
    knopf = (f'<button class="liste-knopf" name="liste" value="{"nein" if drauf else "hand"}" aria-pressed="{str(drauf).lower()}"'
             f' aria-label="{e(voll_name(a))} auf der Einkaufsliste">Liste</button>')
    if a["stueck"]:
        n = a["anzahl"]
        unter = {"da": "", "wenig": f"wenig, mindestens {a['mindestens']}", "leer": "leer"}[s]
        name = f'<span class="name">{e(a["name"])}' + (f'<span class="unter">{unter}</span>' if unter else "") + "</span>"
        mitte = (name + f'<span class="zaehler"><button name="anzahl" value="{max(n - 1, 0)}" aria-label="{e(a["name"])}: eins weniger"'
                 + (" disabled" if n == 0 else "") + f'>−</button><span class="zahl">{n}</span>'
                 + f'<button name="anzahl" value="{n + 1}" aria-label="{e(a["name"])}: eins mehr">+</button></span>')
    else:
        mitte = f'<button class="stand" name="stand" value="{NAECHST[s]}">{name}<span class="wert">{s}</span></button>'
    return (f'<li id="a-{i}" class="artikel ist-{s}{" sorte" if a["ober"] else ""}" data-teil data-suche="{suche(a)}">'
            f'<form class="sofort" method="post" action="{weg}">{feld("id", i)}{mit}{mitte}{knopf}</form></li>')


def bearbeiten_zeile(i, a):
    art = f"Stück, mindestens {a['mindestens']}" if a["stueck"] else ""
    info = ", ".join(x for x in (art, "Basis" if a["basis"] else "", ", ".join(a["auch"])) if x)
    return (f'<li id="a-{i}" class="artikel{" sorte" if a["ober"] else ""}" data-suche="{suche(a)}">'
            f'<a class="bearb" href="/artikel?id={i}"><span class="name">{e(a["name"])}</span>'
            f'<span class="grund">{e(info)}</span></a></li>')


def vorrat_seite(f, bearbeiten):
    f = f if f in ("da", "fehlt") else ""
    v = laden()
    teile = []
    for b, liste in gruppiert(v["artikel"]):
        liste = [(i, a) for i, a in liste if not f or (f == "da") == (stand(a) != "leer")]
        zeilen, ober = [], ""
        for i, a in liste:
            if a["ober"] and a["ober"] != ober:
                sorten = " ".join(voll_name(x) for _, x in liste if x["ober"] == a["ober"])
                zeilen.append(f'<li class="ober" data-suche="{e(sorten.lower())}">{e(a["ober"])}</li>')
            ober = a["ober"]
            zeilen.append(bearbeiten_zeile(i, a) if bearbeiten else zeile(i, a))
        if zeilen:
            teile.append(f'<section class="gruppe"><h2>{e(b)}</h2><ul class="artikelliste">{"".join(zeilen)}</ul></section>')
    extra = "&bearbeiten=1" if bearbeiten else ""
    aktuell = ' aria-current="page"'
    reiter = "".join(f'<a href="/vorrat?f={k}{extra}"{aktuell if k == f else ""}>{name}</a>'
                     for k, name in (("", "Alle"), ("da", "Da"), ("fehlt", "Fehlt")))
    knoepfe = ('<a class="knopf" href="/artikel">Neuer Artikel</a><a class="knopf zweit" href="/vorrat">Fertig</a>'
               if bearbeiten else f'<a class="knopf zweit" href="/vorrat?f={f}&bearbeiten=1">Bearbeiten</a>')
    hinweis = ('<p class="erklaerung">Tippen öffnet den Artikel.</p>' if bearbeiten else
               '<p class="erklaerung">Ein Tipp schaltet weiter: da, wenig, leer. Was ausgeht, kommt auf die Einkaufsliste.</p>')
    return seite("Vorrat", f"""<div class="kopf"><h1>Vorrat</h1><p class="aktionen">{knoepfe}</p></div>
<nav class="reiter" aria-label="Filter">{reiter}</nav>
{hinweis}
<input type="search" id="suche" placeholder="Suchen" aria-label="Im Vorrat suchen">
{"".join(teile) or '<p class="leer">Hier ist nichts.</p>'}
<div id="platz" aria-live="polite"></div>
<script>{SKRIPT}</script>""", "/vorrat")


# --- Einkauf ---

def alt_felder(a):
    return feld("altstand", a["stand"]) + feld("altanzahl", a["anzahl"]) + feld("altliste", a["liste"] or "nein")


def alt_aus(form):
    return {"stand": wert(form, "altstand") if wert(form, "altstand") in NAECHST else "leer",
            "anzahl": zahl(form, "altanzahl") or 0, "liste": LISTE.get(wert(form, "altliste"), "")}


def posten(i, a):
    ziel = feld("anzahl", a["anzahl"] + 1) if a["stueck"] else feld("stand", "da")
    return (f'<li class="posten" data-teil><form class="sofort ab" data-weg method="post" action="/einkauf/abhaken">'
            f'{feld("id", i)}{alt_felder(a)}{ziel}<button class="haken"><span class="name">{e(voll_name(a))}</span>'
            f'<span class="grund">{e(grund(a))}</span></button></form>'
            f'<form class="sofort" data-weg method="post" action="/einkauf/weg">{feld("id", i)}{alt_felder(a)}'
            f'<button class="weg" aria-label="{e(voll_name(a))} von der Liste nehmen">×</button></form></li>')


def posten_einmalig(n):
    return (f'<li class="posten" data-teil><form class="sofort ab" data-weg method="post" action="/einkauf/abhaken">'
            f'{feld("name", n)}<button class="haken"><span class="name">{e(n)}</span><span class="grund">einmalig</span></button></form>'
            f'<form class="sofort" data-weg method="post" action="/einkauf/weg">{feld("name", n)}'
            f'<button class="weg" aria-label="{e(n)} von der Liste nehmen">×</button></form></li>')


def leiste(i, a, alt, was, n=1):
    """Leiste nach dem Abhaken: gekaufte Menge (nur Stueck-Artikel) und Rueckgaengig."""
    teile = [f'<p><b>{e(voll_name(a))}</b> {was}</p>']
    if a["stueck"] and was == "abgehakt":
        teile.append(f'<form class="sofort mengen" method="post" action="/einkauf/menge">{feld("id", i)}{alt_felder(alt)}<span>gekauft:</span>'
                     + "".join(f'<button name="n" value="{k}" aria-pressed="{str(k == n).lower()}">{k}</button>' for k in MENGEN)
                     + "</form>")
    teile.append(f'<form class="sofort" data-neu method="post" action="/vorrat/setzen">{feld("id", i)}{feld("stand", alt["stand"])}'
                 f'{feld("anzahl", alt["anzahl"])}{feld("liste", alt["liste"] or "nein")}<button class="zurueck-knopf">Rückgängig</button></form>')
    return f'<div class="leiste" id="leiste" data-teil>{"".join(teile)}</div>'


def leiste_einmalig(n, was):
    return (f'<div class="leiste" id="leiste" data-teil><p><b>{e(n)}</b> {was}</p>'
            f'<form class="sofort" data-neu method="post" action="/einkauf/dazu">{feld("text", n)}'
            f'<button class="zurueck-knopf">Rückgängig</button></form></div>')


def einkaufsliste():
    """[{name, bereich, grund}] in der Reihenfolge der Seite; fuer /einkauf.json und das Kindle-Bild."""
    v = laden()
    drauf = {i: a for i, a in v["artikel"].items() if a["liste"]}
    return [{"name": voll_name(a), "bereich": b, "grund": grund(a)} for b, liste in gruppiert(drauf) for _, a in liste] + \
        [{"name": n, "bereich": "Sonstiges", "grund": "einmalig"} for n in v.get("einmalig", [])]


def einkauf_listen(v):
    drauf = {i: a for i, a in v["artikel"].items() if a["liste"]}
    teile = [f'<section class="gruppe"><h2>{e(b)}</h2><ul class="artikelliste">{"".join(posten(i, a) for i, a in liste)}</ul></section>'
             for b, liste in gruppiert(drauf)]
    if v["einmalig"]:
        teile.append('<section class="gruppe"><h2>Sonstiges</h2><ul class="artikelliste">'
                     + "".join(posten_einmalig(n) for n in v["einmalig"]) + "</ul></section>")
    return "".join(teile) or '<p class="leer">Die Liste ist leer. Was im Vorrat ausgeht, kommt von selbst drauf.</p>'


def einkauf_seite(teil=False):
    v = laden()
    v.setdefault("einmalig", [])
    if teil:
        return "text/html; charset=utf-8", einkauf_listen(v).encode()
    # Vorschlaege zum Antippen: alles, was nicht auf der Liste steht. Das Skript zeigt sie erst, wenn das Feld
    # angetippt ist (sonst schoebe die Vorauswahl die Liste nach unten): ohne Eingabe die Vorauswahl (wenig oder
    # leer, hoechstens 12), beim Tippen die Treffer. Ohne Skript bleibt die datalist.
    frei = sorted(((i, a) for i, a in v["artikel"].items() if not a["liste"]),
                  key=lambda x: (stand(x[1]) != "wenig", rezepte.name_aus(voll_name(x[1]))))
    knapp = [i for i, a in frei if stand(a) != "da"][:12]
    katalog = "".join(f'<option value="{e(voll_name(a))}">' for _, a in frei)
    vorschlaege = "".join(
        f'<button class="zweit" name="id" value="{i}" data-suche="{suche(a)}"{" data-knapp" if i in knapp else ""} hidden>'
        f'{e(voll_name(a))} <span class="grund">{stand(a)}</span></button>' for i, a in frei)
    return seite("Einkauf", f"""<div class="kopf"><h1>Einkauf</h1></div>
<form class="dazu" method="post" action="/einkauf/dazu">
<input name="text" list="katalog" required maxlength="60" placeholder="Was fehlt noch?" aria-label="Auf die Einkaufsliste">
<button>Dazu</button></form><datalist id="katalog">{katalog}</datalist>
<form class="chips vorschlaege" id="vorschlaege" method="post" action="/einkauf/dazu" aria-label="Vorschläge">{vorschlaege}</form>
<div id="listen">{einkauf_listen(v)}</div>
<div id="platz" aria-live="polite"></div>
<script>{SKRIPT}{EINKAUF_SKRIPT}</script>""", "/einkauf")


def dazu(v, text):
    """Ein Artikel aus dem Katalog kommt von Hand auf die Liste, alles andere wird ein einmaliger Eintrag."""
    text = " ".join(text.split())[:60]
    if not text:
        return
    klein = text.lower()
    treffer = [a for a in v["artikel"].values() if voll_name(a).lower() == klein] or \
              [a for a in v["artikel"].values() if klein in (x.lower() for x in a["auch"])]
    if treffer:
        treffer[0]["liste"] = treffer[0]["liste"] or "hand"
    elif text not in v["einmalig"]:
        v["einmalig"].append(text)


# --- Artikel bearbeiten ---

def artikel_seite(i, name="", zurueck="", kern_=""):
    v = laden()
    a = artikel(v, i) if i else neu_artikel(name.strip()[:60], "", BEREICHE[0])
    bereich_von = {}  # Oberbegriff -> Bereich seiner ersten Sorte
    for x in v["artikel"].values():
        if x["ober"]:
            bereich_von.setdefault(x["ober"], x["bereich"])
    # Vorauswahl fuer einen neuen Artikel: Steckt ein Oberbegriff im Namen („Basmatireis“), ist er vorgeschlagen
    klein = a["name"].lower()
    vorschlag = "" if i else next((o for o in sorted(bereich_von, key=len, reverse=True) if o.lower() in klein and o.lower() != klein), "")
    if vorschlag:
        a["ober"], a["bereich"] = vorschlag, bereich_von[vorschlag]
    hilfe = f" Vorschlag, weil der Name „{e(vorschlag)}“ enthält." if vorschlag else ""
    obers = "".join(f'<option value="{e(o)}">' for o in sorted(bereich_von))
    chips = "".join(f'<button type="button" class="zweit" data-bereich="{e(bereich_von[o])}">{e(o)}</button>' for o in sorted(bereich_von))
    bereiche = "".join(f'<option{" selected" if b == a["bereich"] else ""}>{e(b)}</option>' for b in BEREICHE)
    art = "".join(f'<input type="radio" name="art" id="art-{k}" value="{k}"{" checked" if a["stueck"] == (k == "stueck") else ""}>'
                  f'<label for="art-{k}">{name}</label>' for k, name in (("stufe", "da, wenig, leer"), ("stueck", "Stück zählen")))
    loeschen = (f'<form method="post" action="/artikel/loeschen" onsubmit="return confirm(\'Artikel löschen?\')">{feld("id", i)}'
                '<button class="zweit gefahr">Löschen</button></form>') if i else ""
    hin = ("/zuordnen", "Zuordnen") if zurueck == "zuordnen" else ("/vorrat?bearbeiten=1", "Vorrat")
    return seite(a["name"] or "Neuer Artikel", f"""<p><a class="zurueck" href="{hin[0]}">{hin[1]}</a></p>
<h1>{e(a["name"]) or "Neuer Artikel"}</h1>
<form method="post" action="/artikel/speichern">{feld("id", i)}{feld("zurueck", "zuordnen") if zurueck == "zuordnen" else ""}{feld("kern", kern_[:60]) if kern_ and not i else ""}
<label for="name">Name</label><input id="name" name="name" required maxlength="60" value="{e(a["name"])}">
<label for="ober">Sorte von</label>
<p class="erklaerung" id="ober-hilfe">Nur bei Sorten, z. B. „Spaghetti“ für Dinkel. Rezepte zählen dann jede Sorte.{hilfe}</p>
<input id="ober" name="ober" list="obers" maxlength="60" value="{e(a["ober"])}" aria-describedby="ober-hilfe"><datalist id="obers">{obers}</datalist>
<div class="chips" id="ober-chips" hidden>{chips}</div>
<label for="bereich">Bereich</label><select id="bereich" name="bereich">{bereiche}</select>
<fieldset class="seg"><legend>Art</legend>{art}</fieldset>
<label for="mindestens">Mindestens (nur beim Zählen)</label>
<input id="mindestens" name="mindestens" type="number" min="1" max="99" inputmode="numeric" value="{a["mindestens"]}">
<label for="auch">Auch genannt (mit Komma)</label>
<input id="auch" name="auch" maxlength="300" value="{e(", ".join(a["auch"]))}">
<p class="feld-haken"><input type="checkbox" id="basis" name="basis" value="ja"{" checked" if a["basis"] else ""}>
<label for="basis">Basis: zählt bei Rezepten immer als da (Salz, Pfeffer)</label></p>
<div class="knoepfe"><button>Speichern</button></div></form>
{loeschen}
<script>{ARTIKEL_SKRIPT}</script>""", "/vorrat")


def artikel_speichern(v, form):
    i, name, ober, bereich = wert(form, "id"), wert(form, "name").strip()[:60], wert(form, "ober").strip()[:60], wert(form, "bereich")
    if not name or bereich not in BEREICHE:
        raise ValueError("Name oder Bereich fehlt")
    if i:
        a = artikel(v, i)
    else:
        a = neu_artikel(name, ober, bereich)
        i = basis = kennung(a)
        n = 1
        while i in v["artikel"]:
            n += 1
            i = f"{basis}-{n}"
        v["artikel"][i] = a
    vorher = stand(a)
    stueck = wert(form, "art") == "stueck"
    if stueck and not a["stueck"]:
        a["anzahl"] = max(zahl(form, "mindestens") or 1, 1) if vorher == "da" else 0
    elif a["stueck"] and not stueck:
        a["stand"] = vorher
    a.update(name=name, ober=ober, bereich=bereich, stueck=stueck, mindestens=max(1, min(zahl(form, "mindestens") or 1, 99)),
             auch=[x.strip()[:60] for x in wert(form, "auch").split(",") if x.strip()], basis=wert(form, "basis") == "ja")
    k = " ".join(wert(form, "kern").split())[:60]  # aus „Zuordnen“: die Zutat, fuer die der Artikel entsteht
    if k and k.lower() not in [name.lower()] + [x.lower() for x in a["auch"]]:
        a["auch"].append(k)
    return i


# --- Wege ---

def get(weg, q):
    w = lambda k: q.get(k, [""])[0]  # noqa: E731
    if weg == "/vorrat":
        return vorrat_seite(w("f"), w("bearbeiten") == "1")
    if weg == "/einkauf":
        return einkauf_seite(w("teil") == "1")
    if weg == "/einkauf.json":
        return "application/json; charset=utf-8", json.dumps(
            {"anzahl": len(liste := einkaufsliste()), "artikel": liste}, ensure_ascii=False).encode()
    if weg == "/gekocht":
        return gekocht_seite(w("d"))
    if weg == "/artikel":
        return artikel_seite(w("id"), w("name"), w("zurueck"), w("kern"))
    if weg == "/zuordnen":
        return zuordnen_seite()
    if weg == "/kochen":
        return kochen_seite(q.get("w", []), w("teil") == "1")
    raise FileNotFoundError(weg)


def post(weg, form):
    teil = wert(form, "teil") == "1"
    with SPERRE:
        v = laden()
        v.setdefault("einmalig", [])
        if weg == "/vorrat/setzen":
            i = wert(form, "id")
            a = artikel(v, i)
            setzen(a, wert(form, "stand"), zahl(form, "anzahl"), LISTE.get(wert(form, "liste")))
            antwort, ziel = zeile(i, a), "/vorrat"
        elif weg in ("/einkauf/abhaken", "/einkauf/weg"):
            was = "abgehakt" if weg == "/einkauf/abhaken" else "von der Liste genommen"
            n = wert(form, "name")
            if n:
                if n in v["einmalig"]:
                    v["einmalig"].remove(n)
                antwort = leiste_einmalig(n, was)
            else:
                i = wert(form, "id")
                a = artikel(v, i)
                setzen(a, wert(form, "stand"), zahl(form, "anzahl"), "")
                antwort = leiste(i, a, alt_aus(form), was)
            ziel = "/einkauf"
        elif weg == "/einkauf/menge":
            i, alt, n = wert(form, "id"), alt_aus(form), zahl(form, "n") or 1
            a = artikel(v, i)
            setzen(a, anzahl=alt["anzahl"] + n, liste="")
            antwort, ziel = leiste(i, a, alt, "abgehakt", n), "/einkauf"
        elif weg == "/einkauf/dazu":
            if wert(form, "id"):  # ein Vorschlag wurde angetippt
                a = artikel(v, wert(form, "id"))
                a["liste"] = a["liste"] or "hand"
            else:
                dazu(v, wert(form, "text"))
            antwort, ziel = "", "/einkauf"
        elif weg == "/einkauf/rezept":
            d = wert(form, "d")
            r = rezepte.lesen(rezepte.text(d))[0]
            for k, _ in pruefung(r, v, woerter(v["artikel"]))["fehlt"]:
                a = v["artikel"][k]
                if not a["liste"]:
                    a["liste"], a["fuer"] = "hand", r["titel"]
            antwort, ziel = "", rezepte.zum_rezept(d, wert(form, "portionen"))
        elif weg in ("/zuordnen/zuordnen", "/zuordnen/egal"):
            k = " ".join(wert(form, "kern").split())[:60]
            text = wert(form, "text").strip().lower()
            treffer = [a for a in v["artikel"].values() if voll_name(a).lower() == text and a["bereich"] not in NICHT_ESSBAR]
            ziel = "/zuordnen"
            if not k:
                raise FileNotFoundError("kern")
            if weg == "/zuordnen/egal":
                if k.lower() not in v.setdefault("egal", []):
                    v["egal"].append(k.lower())
            elif treffer:
                if k.lower() not in (x.lower() for x in treffer[0]["auch"]):
                    treffer[0]["auch"].append(k)
            else:  # gibt es noch nicht: als neuen Artikel anlegen, die Zutat wird sein Synonym
                ziel = f"/artikel?name={quote(wert(form, 'text').strip()[:60])}&kern={quote(k)}&zurueck=zuordnen"
            antwort = ""
        elif weg == "/artikel/speichern":
            i = artikel_speichern(v, form)
            antwort, ziel = "", "/zuordnen" if wert(form, "zurueck") == "zuordnen" else f"/vorrat?bearbeiten=1#a-{i}"
        elif weg == "/artikel/loeschen":
            artikel(v, wert(form, "id"))
            del v["artikel"][wert(form, "id")]
            antwort, ziel = "", "/vorrat?bearbeiten=1"
        else:
            raise FileNotFoundError(weg)
        speichern(v)
    return ("text/html; charset=utf-8", antwort.encode()) if teil else weiter(ziel)


SKRIPT = """
// Tipps ohne Neuladen: Antwort ersetzt die Zeile; data-weg nimmt sie weg und zeigt die Leiste, data-neu laedt neu.
const platz = document.getElementById('platz');
let uhr;
function zeigen(html) {
  clearTimeout(uhr);
  platz.innerHTML = html;
  uhr = setTimeout(() => { platz.innerHTML = ''; }, 8000);
}
document.addEventListener('submit', async ev => {
  const f = ev.target;
  if (!f.classList.contains('sofort')) return;
  ev.preventDefault();
  const daten = new URLSearchParams(new FormData(f));
  if (ev.submitter && ev.submitter.name) daten.append(ev.submitter.name, ev.submitter.value);
  daten.append('teil', '1');
  const ziel = f.closest('[data-teil]');
  ziel.classList.remove('nicht-gespeichert');
  for (let versuch = 0; versuch < 3; versuch++) {
    try {
      const a = await fetch(f.action, {method: 'POST', body: daten});
      if (!a.ok) throw new Error(a.status);
      const html = await a.text();
      if ('neu' in f.dataset) return location.reload();
      if ('weg' in f.dataset) {
        const gruppe = ziel.closest('.gruppe');
        ziel.remove();
        if (!gruppe.querySelector('.posten')) gruppe.remove();
        return zeigen(html);
      }
      if (ziel.id === 'leiste') return zeigen(html);
      ziel.outerHTML = html;
      return;
    } catch (fehler) {
      await new Promise(weiter => setTimeout(weiter, 1000));  // WLAN weg: gleicher Wert, also gefahrlos wiederholen
    }
  }
  ziel.classList.add('nicht-gespeichert');
});
""" + rezepte.SUCH_SKRIPT

ARTIKEL_SKRIPT = """
// „Sorte von“: Oberbegriffe zum Antippen. Der Tipp fuellt das Feld und stellt den Bereich der Sorten ein, ein zweiter
// leert es. Steckt ein Oberbegriff im Namen, ist sein Chip hervorgehoben; von selbst ausgefuellt wird beim Tippen nichts.
const ober = document.getElementById('ober'), kiste = document.getElementById('ober-chips');
function chips_zeigen() {
  const name = document.getElementById('name').value.toLowerCase();
  for (const c of kiste.children) {
    c.setAttribute('aria-pressed', String(c.textContent === ober.value.trim()));
    c.classList.toggle('passt', name.includes(c.textContent.toLowerCase()));
  }
}
kiste.hidden = !kiste.children.length;
kiste.addEventListener('click', ev => {
  const c = ev.target.closest('button');
  if (!c) return;
  const an = c.getAttribute('aria-pressed') === 'true';
  ober.value = an ? '' : c.textContent;
  if (!an) document.getElementById('bereich').value = c.dataset.bereich;
  chips_zeigen();
});
ober.addEventListener('input', chips_zeigen);
document.getElementById('name').addEventListener('input', chips_zeigen);
chips_zeigen();
"""

KOCHEN_SKRIPT = """
// Auswahl ohne Neuladen: Treffer holen, Adresse mitfuehren (Neuladen behaelt die Auswahl)
const auswahl = document.getElementById('auswahl');
document.getElementById('zeigen').hidden = true;
auswahl.addEventListener('change', async () => {
  const q = new URLSearchParams(new FormData(auswahl)).toString();
  history.replaceState(null, '', '/kochen' + (q ? '?' + q : ''));
  try {
    const a = await fetch('/kochen?teil=1' + (q ? '&' + q : ''));
    if (a.ok) document.getElementById('treffer').innerHTML = await a.text();
  } catch (fehler) {}
});
"""

EINKAUF_SKRIPT = """
// Hakt die andere Person etwas ab, steht es nach spaetestens 10 s auch hier; nicht waehrend der Leiste nach dem Abhaken.
let zuletzt = null;  // letzte Antwort des Servers; innerHTML des Browsers sieht nie ganz gleich aus
async function auffrischen() {
  if (document.hidden || platz.innerHTML) return;
  try {
    const a = await fetch('/einkauf?teil=1');
    const html = a.ok ? await a.text() : zuletzt;
    if (html !== zuletzt) { document.getElementById('listen').innerHTML = html; zuletzt = html; }
  } catch (fehler) {}
}
setInterval(auffrischen, 10000);
document.addEventListener('visibilitychange', auffrischen);
// Vorschlaege unter dem Feld, sobald es angetippt ist: bei leerem Feld die Vorauswahl, beim Tippen die Treffer (hoechstens 8)
const feld = document.querySelector('.dazu input'), vorschlaege = document.querySelectorAll('#vorschlaege button');
feld.removeAttribute('list');  // sonst kaemen die Vorschlaege doppelt
function vorschlagen() {
  const q = feld.value.trim().toLowerCase();
  let n = 0;
  for (const b of vorschlaege) b.hidden = q ? !(b.dataset.suche.includes(q) && n++ < 8) : !('knapp' in b.dataset);
}
feld.addEventListener('focus', vorschlagen);
feld.addEventListener('input', vorschlagen);
"""
