# Änderungen

Versionen nach [Semantic Versioning](https://semver.org/lang/de/). Jede Version gibt es als fertiges Image:
`ghcr.io/auktoriator/pichef:<Version>` (ab 1.1.0).

## 1.1.0 – 2026-11-13

### Neu
- **Fertige Images** für Raspberry Pi (arm64) und PC (amd64) in der GitHub Container Registry, gebaut und getestet
  von GitHub Actions, mit Herkunftsnachweis. Auf dem Pi muss nichts mehr gebaut werden: `compose.yaml` lädt
  `ghcr.io/auktoriator/pichef:1`.
- **Automatische Tests** bei jedem Push und Pull Request: App, Kindle-Skripte unter busybox, Start des Containers.

### Geändert
- Python-Pakete stehen in `requirements.txt`, das Basis-Image ist per Digest festgelegt, Updates kommen über
  Dependabot.

## 1.0.0 – 2026-11-13

Erste öffentliche Fassung: Rezepte per Prompt (auch mehrere auf einmal, auf Wunsch nur aus dem Vorrat oder aus allen
Artikeln), Vorrat, Einkaufsliste, „Was kann ich heute kochen?“, Kochmodus, Kindle als Küchen-Display, Einkaufsliste
für Home Assistant.
