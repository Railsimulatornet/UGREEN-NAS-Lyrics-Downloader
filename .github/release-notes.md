## Deutsch

### Was ist neu?

Dieses Update aktualisiert die Bibliotheken für Downloads und Musik-Tags und verbessert die automatische Pflege der Docker-Images.

- Requests wurde auf `2.34.2` und Mutagen auf `1.48.1` aktualisiert.
- Die Images für AMD64 und ARM64 werden vor der Veröffentlichung auf behebbare schwere und kritische Sicherheitslücken geprüft.
- Docker Hub und die GitHub Container Registry erhalten dasselbe geprüfte Image.
- `latest` wird zusätzlich einmal pro Woche frisch gebaut und geprüft. Feste Versionstags bleiben unverändert; Wartungsbuilds erhalten lesbare Tags mit Version und Datum.

An den Download-, LRC- und Berichtsfunktionen sowie den bisherigen Einstellungen ändert sich nichts.

### Aktualisierung

Der lokale Build über das mitgelieferte Compose-Projekt bleibt erhalten. Bei bestehenden lokalen Installationen die neue `Dockerfile` und `requirements.txt` übernehmen und den bestehenden Lyrics-Downloader-Dienst neu bauen. Die Versionsangaben im eigenen Compose-Projekt können auf `1.0.2` angepasst werden.

Wer bereits ein vorgebautes Image verwendet, kann bei `latest` bleiben oder gezielt `1.0.2` verwenden. Beide Quellen bleiben bestehen: `railsimulatornet/ugreen-nas-lyrics-downloader` und `ghcr.io/railsimulatornet/ugreen-nas-lyrics-downloader`.

**Die eigene `.env`, angepasste Mounts, Musikdateien und vorhandene `.lrc`-Dateien bitte beibehalten.** Das ZIP-Paket und das deutsch-englische PDF-Handbuch stehen wie bisher zur Verfügung.

---

## English

### What is new?

This update refreshes the download and audio-tag libraries and improves automated Docker image maintenance.

- Updated Requests to `2.34.2` and Mutagen to `1.48.1`.
- AMD64 and ARM64 images are checked for fixable high and critical vulnerabilities before publication.
- Docker Hub and GitHub Container Registry receive the same verified image.
- `latest` is also rebuilt and checked weekly. Fixed version tags stay unchanged; maintenance builds receive readable version-and-date tags.

Download, LRC and reporting features, as well as existing settings, remain unchanged.

### Updating

The included Compose project continues to support local builds. For an existing local installation, update `Dockerfile` and `requirements.txt`, then rebuild the existing Lyrics Downloader service. Version entries in the existing Compose project can be updated to `1.0.2`.

Existing users of prebuilt images can keep `latest` or select `1.0.2`. Both sources remain available: `railsimulatornet/ugreen-nas-lyrics-downloader` and `ghcr.io/railsimulatornet/ugreen-nas-lyrics-downloader`.

**Keep the existing `.env`, customized mounts, music and `.lrc` files.** The ZIP package and German-English PDF manual remain available.
