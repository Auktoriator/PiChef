# Änderungen

Versionen nach [Semantic Versioning](https://semver.org/lang/de/). Jede Version gibt es als fertiges Image:
`ghcr.io/auktoriator/pichef:<Version>` (ab 1.1.0).

## 1.1.0 – 2026-11-13

### Neu
- **Neues Rezept:** Wahl „Zutaten“. „Was da ist“ schickt den aktuellen Vorrat in den Prompt, „alle Artikel“ den
  ganzen Katalog (alles, was ihr sonst im Haus habt), „egal“ lässt freie Hand.
- **Fertige Images** für Raspberry Pi (arm64) und PC (amd64) in der GitHub Container Registry, gebaut und getestet
  von GitHub Actions, mit Herkunftsnachweis. Auf dem Pi muss nichts mehr gebaut werden.

### Geändert
- Aus „Kochen“ heraus ist im Prompt „was da ist“ vorgewählt, die Wahl „1–2 dazukaufen“ / „nichts kaufen“ ist
  sichtbar vorgewählt.
- Python-Pakete stehen in `requirements.txt`, das Basis-Image ist per Digest festgelegt (Updates über Dependabot).

## 1.0.0 – 2026-11-13

Erste öffentliche Fassung: Rezepte per Prompt, Vorrat, Einkaufsliste, „Was kann ich heute kochen?“, Kochmodus,
Kindle als Küchen-Display, Einkaufsliste für Home Assistant.
