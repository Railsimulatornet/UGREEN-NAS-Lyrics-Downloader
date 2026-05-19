UGREEN NAS Lyrics Downloader 1.0.0
==================================
Copyright (c) 2026 Roman Glos

Deutsch
-------
Dieses Docker-Tool scannt eine Musikbibliothek, liest Titel, Künstler, Album und Dauer aus den Audiodateien und lädt passende LRC-Lyrics über LRCLIB herunter.

Standardmäßig werden nur echte synchronisierte LRC-Dateien neben den Songs gespeichert, zum Beispiel:

  /volume1/Emby/Musik/Single Jahrescharts 2023/79. AYLIVA - Bei Nacht.mp3
  /volume1/Emby/Musik/Single Jahrescharts 2023/79. AYLIVA - Bei Nacht.lrc

Das ist für den Test mit der UGREEN Music App sinnvoller als reine ID3-USLT-Texte, da synchronisierte LRC-Dateien von vielen Musik-Playern zuverlässiger als Liedtextquelle erkannt werden.

Funktionen
----------
- Scan einer lokalen Musikbibliothek im Container unter /music
- Unterstützte Formate: MP3, FLAC, M4A, MP4, OGG, OPUS
- Download synchronisierter LRC-Lyrics über LRCLIB
- Speicherung als Sidecar-Datei neben der Musikdatei
- Optionales Schreiben von Lyrics in Audiodatei-Tags
- Überspringen vorhandener .lrc-Dateien
- JSON-Bericht unter /reports/last_report.json
- Geeignet für UGOS / UGREEN NAS Docker-Projekte

Installation auf UGOS / UGREEN NAS
----------------------------------
1. Ordner auf das NAS kopieren, zum Beispiel nach:

   /volume2/docker/UGREEN-NAS-Lyrics-Downloader

2. In den Ordner wechseln:

   cd /volume2/docker/UGREEN-NAS-Lyrics-Downloader

3. .env prüfen und bei Bedarf anpassen:

   nano .env

   Wichtig sind vor allem:

   HOST_MUSIC_DIR=/volume1/Emby/Musik
   PUID=1009
   PGID=10

4. Container bauen und einmal ausführen:

   docker compose up --build

5. Nach dem Lauf prüfen:

   find /volume1/Emby/Musik -name "*.lrc" | head

6. Danach in UGREEN Music die Bibliothek erneut prüfen. Falls die App die neuen .lrc-Dateien nicht sofort erkennt, die Musikbibliothek neu einlesen lassen oder die UGREEN Music App kurz neu starten.

Empfohlene Testeinstellung
--------------------------
Für einen sauberen Test der UGREEN-Lyrics-Erkennung:

  REQUIRE_SYNCED_LYRICS=true
  WRITE_PLAIN_AS_LRC=false
  WRITE_SIDECAR_LRC=true
  WRITE_EMBEDDED_TAGS=false
  SKIP_EXISTING_LRC=true
  TOUCH_AUDIO_ON_WRITE=true

So werden nur echte synchronisierte LRC-Dateien geschrieben. Wenn UGREEN Music diese Dateien nicht erkennt oder weiterhin "Keine Liedtexte gefunden" anzeigt, ist das ein guter Hinweis auf ein Problem in der UGREEN Music App, im Indexer oder im Lyrics-Parser.

Prüfung für einen bestimmten Song
---------------------------------
Beispiel für AYLIVA:

  find /volume1/Emby/Musik -type f \( -iname "*AYLIVA*.lrc" -o -iname "*Bei*Nacht*.lrc" \) -print

Logs anzeigen
-------------

  docker compose logs -f

Bericht anzeigen
----------------

  cat reports/last_report.json

Cron-Beispiel
-------------
Einmal pro Nacht um 03:30 Uhr:

  30 3 * * * cd /volume2/docker/UGREEN-NAS-Lyrics-Downloader && docker compose up --build --abort-on-container-exit >> /volume2/docker/UGREEN-NAS-Lyrics-Downloader/reports/cron.log 2>&1

Hinweis zu langen Album-Dateien
-------------------------------
Bei sehr langen Dateien, zum Beispiel kompletten Alben in einer einzelnen MP3-Datei, kann ein Treffer für einen einzelnen Song gefunden werden. Für reine UGREEN-Tests ist das unkritisch. Für eine dauerhaft gepflegte Musikbibliothek sollten solche Dateien besser in einzelne Titel aufgeteilt werden.

English
-------
This Docker tool scans a music library, reads title, artist, album and duration from audio tags and downloads matching LRC lyrics from LRCLIB.

By default, it only writes real synchronized LRC sidecar files next to the songs, for example:

  /volume1/Emby/Musik/Single Jahrescharts 2023/79. AYLIVA - Bei Nacht.mp3
  /volume1/Emby/Musik/Single Jahrescharts 2023/79. AYLIVA - Bei Nacht.lrc

Features
--------
- Scans a local music library mounted as /music
- Supported formats: MP3, FLAC, M4A, MP4, OGG, OPUS
- Downloads synchronized LRC lyrics from LRCLIB
- Saves sidecar .lrc files next to the audio files
- Optional embedded lyric tags
- Skips existing .lrc files
- JSON report at /reports/last_report.json
- Suitable for UGOS / UGREEN NAS Docker projects

Installation on UGOS / UGREEN NAS
---------------------------------
1. Copy the folder to your NAS, for example:

   /volume2/docker/UGREEN-NAS-Lyrics-Downloader

2. Enter the folder:

   cd /volume2/docker/UGREEN-NAS-Lyrics-Downloader

3. Check and adjust .env if needed:

   nano .env

   Important settings:

   HOST_MUSIC_DIR=/volume1/Emby/Musik
   PUID=1009
   PGID=10

4. Build and run the container once:

   docker compose up --build

5. Check the generated .lrc files:

   find /volume1/Emby/Musik -name "*.lrc" | head

Recommended test configuration
------------------------------

  REQUIRE_SYNCED_LYRICS=true
  WRITE_PLAIN_AS_LRC=false
  WRITE_SIDECAR_LRC=true
  WRITE_EMBEDDED_TAGS=false
  SKIP_EXISTING_LRC=true
  TOUCH_AUDIO_ON_WRITE=true

Run:

  docker compose up --build

Then check whether UGREEN Music detects and displays the generated .lrc files.
