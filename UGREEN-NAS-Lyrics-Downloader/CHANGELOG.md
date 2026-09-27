# Changelog

## 1.0.2 - 2026-09-27

### Deutsch

- Requests auf 2.34.2 und Mutagen auf 1.48.1 aktualisiert.
- AMD64- und ARM64-Images werden vor der Veröffentlichung geprüft; beide Registries erhalten dasselbe geprüfte Image.
- Wöchentliche Wartungsbuilds für `latest` mit lesbaren Versions- und Datumstags ergänzt. Feste Release-Tags bleiben unverändert.
- Build-Kontext auf die benötigten Anwendungsdateien begrenzt.
- ZIP-Paket und bestehendes DE/EN-Handbuch werden nach erfolgreicher Image-Veröffentlichung automatisch bereitgestellt.
- Download-, LRC- und Berichtsfunktionen sowie der lokale Compose-Build bleiben erhalten.

### English

- Updated Requests to 2.34.2 and Mutagen to 1.48.1.
- AMD64 and ARM64 images are checked before publication; both registries receive the same verified image.
- Added weekly maintenance builds for `latest` with readable version-and-date tags. Fixed release tags remain unchanged.
- Limited the build context to required application files.
- ZIP package and existing DE/EN manual are published automatically after image publication succeeds.
- Download, LRC and reporting features, as well as local Compose builds, remain available.

## 1.0.1 - 2026-08-30

- Sicherheitsupdate für das Container-Image.
- Debian- und Python-Abhängigkeiten aktualisiert.
- Nicht benötigte Python-Build-Werkzeuge aus dem Runtime-Image entfernt.
- Keine Änderungen an Download-, LRC- oder Berichtsfunktionen.

## 1.0.0 - 2026-05-18

- Erste stabile Version für UGREEN NAS / UGOS.
- Synchronisierte LRC-Lyrics über LRCLIB.
- Sidecar-Dateien neben den Musikdateien, zum Beispiel `Song.mp3` zu `Song.lrc`.
- JSON-Bericht unter `reports/last_report.json`.
- Docker-Compose-Projekt für UGREEN NAS.
