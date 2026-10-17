## Deutsch

### Sicherheitsupdate

Die mitgelieferte Docker-Compose-Datei wurde abgesichert:

- Container-Dateisystem schreibgeschützt, keine zusätzlichen Linux-Berechtigungen und keine Rechteausweitung.
- Musikordner, Konfiguration und Berichte bleiben wie bisher nutzbar.
- Keine Änderungen am Lyrics-Download oder an den Python-Abhängigkeiten.

### Aktualisierung

Bei einer bestehenden Installation die neuen Sicherheitsoptionen in die eigene `docker-compose.yaml` übernehmen und den Container neu erstellen. Die eigene `.env`, angepasste Mounts, Musikdateien und vorhandene `.lrc`-Dateien beibehalten.

Wer ein vorgebautes Image nutzt, muss die Sicherheitsoptionen ebenfalls in der eigenen Compose-Datei setzen. Das Image allein aktiviert diese Einstellungen nicht.

Die noch offenen Debian-Sicherheitsmeldungen werden durch dieses Update nicht behoben.

---

## English

### Security update

The included Docker Compose configuration has been hardened:

- Read-only container root filesystem, no additional Linux capabilities and no privilege escalation.
- Music, configuration and report mounts remain available.
- No changes to lyrics downloading or Python dependencies.

### Updating

For existing installations, apply the new security settings to the current `docker-compose.yaml` and recreate the container. Keep the existing `.env`, custom mounts, music files and `.lrc` files.

Users of prebuilt images must also apply the security options in their own Compose file. The image alone does not enforce these settings.

This update does not fix the outstanding Debian vulnerability reports.
