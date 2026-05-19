#!/usr/bin/env python3
"""
UGREEN NAS Lyrics Downloader
Copyright (c) 2026 Railsimulatornet
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

import requests
from mutagen import File as MutagenFile
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, USLT
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

APP_NAME = "UGREEN NAS Lyrics Downloader"
APP_VERSION = "1.0.0"
SCRIPT_COPYRIGHT = "Copyright (c) 2026 Railsimulatornet"
LRCLIB_BASE_URL = "https://lrclib.net/"


@dataclass
class Config:
    music_dir: Path
    audio_extensions: set[str]
    require_synced_lyrics: bool
    write_plain_as_lrc: bool
    write_sidecar_lrc: bool
    write_embedded_tags: bool
    skip_existing_lrc: bool
    touch_audio_on_write: bool
    dry_run: bool
    request_delay_seconds: float
    scan_interval_seconds: int
    max_files_per_run: int
    save_report: bool
    report_path: Path
    user_agent: str
    log_level: str


@dataclass
class TrackInfo:
    path: str
    title: str
    artist: str
    album: str
    duration: int | None
    extension: str


@dataclass
class FileResult:
    path: str
    status: str
    message: str
    lrc_path: str | None = None
    source_id: int | None = None
    synced: bool = False


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError:
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip().replace(",", "."))
    except ValueError:
        return default


def load_config() -> Config:
    extensions = {
        ext.strip().lower() if ext.strip().startswith(".") else f".{ext.strip().lower()}"
        for ext in os.getenv("AUDIO_EXTENSIONS", ".mp3,.flac,.m4a,.mp4,.ogg,.opus").split(",")
        if ext.strip()
    }
    return Config(
        music_dir=Path(os.getenv("MUSIC_DIR", "/music")),
        audio_extensions=extensions,
        require_synced_lyrics=env_bool("REQUIRE_SYNCED_LYRICS", True),
        write_plain_as_lrc=env_bool("WRITE_PLAIN_AS_LRC", False),
        write_sidecar_lrc=env_bool("WRITE_SIDECAR_LRC", True),
        write_embedded_tags=env_bool("WRITE_EMBEDDED_TAGS", False),
        skip_existing_lrc=env_bool("SKIP_EXISTING_LRC", True),
        touch_audio_on_write=env_bool("TOUCH_AUDIO_ON_WRITE", True),
        dry_run=env_bool("DRY_RUN", False),
        request_delay_seconds=env_float("REQUEST_DELAY_SECONDS", 1.0),
        scan_interval_seconds=env_int("SCAN_INTERVAL_SECONDS", 0),
        max_files_per_run=env_int("MAX_FILES_PER_RUN", 0),
        save_report=env_bool("SAVE_REPORT", True),
        report_path=Path(os.getenv("REPORT_PATH", "/reports/last_report.json")),
        user_agent=os.getenv("USER_AGENT", f"{APP_NAME}/{APP_VERSION}"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )


def first_text(values: Any) -> str:
    if values is None:
        return ""
    if isinstance(values, (list, tuple)):
        for value in values:
            text = str(value).strip()
            if text:
                return text
        return ""
    return str(values).strip()


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"\([^)]*\)|\[[^]]*]", " ", value)
    value = re.sub(r"[^a-z0-9Ã¤Ã¶Ã¼ÃŸ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def clean_filename_title(stem: str) -> tuple[str, str]:
    text = re.sub(r"^\s*\d+\s*[.\-_)]\s*", "", stem).strip()
    if " - " in text:
        artist, title = text.split(" - ", 1)
        return title.strip(), artist.strip()
    return text, ""


def get_easy_tag(audio: Any, key: str) -> str:
    try:
        return first_text(audio.tags.get(key)) if audio.tags else ""
    except Exception:
        return ""


def read_track_info(path: Path) -> TrackInfo | None:
    try:
        audio = MutagenFile(path, easy=True)
        raw_audio = MutagenFile(path, easy=False)
    except Exception as exc:
        logging.warning("Metadaten konnten nicht gelesen werden: %s (%s)", path, exc)
        return None

    if audio is None and raw_audio is None:
        logging.warning("Keine Audiodatei erkannt: %s", path)
        return None

    title = get_easy_tag(audio, "title") if audio else ""
    artist = get_easy_tag(audio, "artist") if audio else ""
    album = get_easy_tag(audio, "album") if audio else ""

    # Fallback for MP4 atoms when easy tags are incomplete.
    try:
        if raw_audio and raw_audio.tags:
            title = title or first_text(raw_audio.tags.get("\xa9nam"))
            artist = artist or first_text(raw_audio.tags.get("\xa9ART"))
            album = album or first_text(raw_audio.tags.get("\xa9alb"))
    except Exception:
        pass

    fallback_title, fallback_artist = clean_filename_title(path.stem)
    title = title or fallback_title
    artist = artist or fallback_artist

    duration = None
    try:
        if raw_audio and raw_audio.info and getattr(raw_audio.info, "length", None):
            duration = int(round(float(raw_audio.info.length)))
    except Exception:
        duration = None

    if not title or not artist:
        logging.info("Ãœbersprungen, Titel oder KÃ¼nstler fehlt: %s", path)
        return None

    return TrackInfo(
        path=str(path),
        title=title.strip(),
        artist=artist.strip(),
        album=album.strip(),
        duration=duration,
        extension=path.suffix.lower(),
    )


def iter_audio_files(music_dir: Path, extensions: set[str]) -> Iterable[Path]:
    for path in music_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            yield path


def lrclib_get_exact(session: requests.Session, track: TrackInfo) -> dict[str, Any] | None:
    params: dict[str, Any] = {
        "artist_name": track.artist,
        "track_name": track.title,
    }
    if track.album:
        params["album_name"] = track.album
    if track.duration:
        params["duration"] = track.duration

    response = session.get(urljoin(LRCLIB_BASE_URL, "api/get"), params=params, timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def result_score(track: TrackInfo, item: dict[str, Any]) -> int:
    score = 0
    if normalize_text(track.title) == normalize_text(str(item.get("trackName", ""))):
        score += 50
    elif normalize_text(track.title) in normalize_text(str(item.get("trackName", ""))):
        score += 20

    if normalize_text(track.artist) == normalize_text(str(item.get("artistName", ""))):
        score += 40
    elif normalize_text(track.artist) in normalize_text(str(item.get("artistName", ""))):
        score += 15

    if track.album and normalize_text(track.album) == normalize_text(str(item.get("albumName", ""))):
        score += 10

    try:
        result_duration = int(round(float(item.get("duration") or 0)))
        if track.duration and result_duration:
            delta = abs(track.duration - result_duration)
            if delta <= 2:
                score += 20
            elif delta <= 5:
                score += 10
    except Exception:
        pass

    return score


def lrclib_search_fallback(session: requests.Session, track: TrackInfo) -> dict[str, Any] | None:
    params = {
        "artist_name": track.artist,
        "track_name": track.title,
    }
    response = session.get(urljoin(LRCLIB_BASE_URL, "api/search"), params=params, timeout=30)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    results = response.json()
    if not isinstance(results, list) or not results:
        return None

    ranked = sorted(results, key=lambda item: result_score(track, item), reverse=True)
    best = ranked[0]
    if result_score(track, best) < 60:
        return None
    return best


def find_lyrics(session: requests.Session, track: TrackInfo) -> dict[str, Any] | None:
    try:
        exact = lrclib_get_exact(session, track)
        if exact:
            return exact
    except requests.HTTPError as exc:
        logging.debug("Exakte LRCLIB-Suche fehlgeschlagen fÃ¼r %s - %s: %s", track.artist, track.title, exc)
    except requests.RequestException as exc:
        logging.warning("LRCLIB-Anfrage fehlgeschlagen fÃ¼r %s - %s: %s", track.artist, track.title, exc)
        return None

    try:
        return lrclib_search_fallback(session, track)
    except requests.RequestException as exc:
        logging.warning("LRCLIB-Fallback fehlgeschlagen fÃ¼r %s - %s: %s", track.artist, track.title, exc)
        return None


def ensure_lrc_header(content: str, track: TrackInfo) -> str:
    content = (content or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    header: list[str] = []
    existing = content.lower()
    if "[ti:" not in existing:
        header.append(f"[ti:{track.title}]")
    if "[ar:" not in existing:
        header.append(f"[ar:{track.artist}]")
    if track.album and "[al:" not in existing:
        header.append(f"[al:{track.album}]")
    if track.duration and "[length:" not in existing:
        minutes, seconds = divmod(track.duration, 60)
        header.append(f"[length:{minutes:02d}:{seconds:02d}]")
    if "[by:" not in existing:
        header.append(f"[by:{APP_NAME}]")
    if header:
        return "\n".join(header) + "\n" + content + "\n"
    return content + "\n"


def plain_to_lrc(plain: str, track: TrackInfo) -> str:
    lines = [line.strip() for line in (plain or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    lines = [line for line in lines if line]
    header = [f"[ti:{track.title}]", f"[ar:{track.artist}]", f"[by:{APP_NAME}]"]
    if track.album:
        header.append(f"[al:{track.album}]")
    if not lines:
        return "\n".join(header) + "\n"
    rendered = [f"[00:00.00]{lines[0]}"]
    for line in lines[1:]:
        rendered.append(line)
    return "\n".join(header + rendered) + "\n"


def write_sidecar_lrc(path: Path, content: str, config: Config) -> Path:
    lrc_path = path.with_suffix(".lrc")
    if config.dry_run:
        logging.info("DRY_RUN: WÃ¼rde LRC schreiben: %s", lrc_path)
        return lrc_path
    lrc_path.write_text(content, encoding="utf-8", newline="\n")
    return lrc_path


def write_embedded_tags(path: Path, plain_lyrics: str, synced_lyrics: str | None, config: Config) -> None:
    if config.dry_run:
        logging.info("DRY_RUN: WÃ¼rde Tags schreiben: %s", path)
        return

    suffix = path.suffix.lower()
    lyrics_text = plain_lyrics or synced_lyrics or ""
    if not lyrics_text.strip():
        return

    if suffix == ".mp3":
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        tags.delall("USLT")
        tags.add(USLT(encoding=3, lang="XXX", desc="", text=lyrics_text))
        tags.save(path)
        return

    audio = MutagenFile(path)
    if audio is None:
        return

    if isinstance(audio, FLAC | OggVorbis | OggOpus):
        audio["LYRICS"] = lyrics_text
        if synced_lyrics:
            audio["LYRICS_SYNCED"] = synced_lyrics
        audio.save()
        return

    if isinstance(audio, MP4):
        audio["\xa9lyr"] = [lyrics_text]
        audio.save()


def process_file(path: Path, session: requests.Session, config: Config) -> FileResult:
    lrc_path = path.with_suffix(".lrc")
    if config.write_sidecar_lrc and config.skip_existing_lrc and lrc_path.exists():
        return FileResult(str(path), "skipped", "LRC existiert bereits", str(lrc_path))

    track = read_track_info(path)
    if track is None:
        return FileResult(str(path), "skipped", "Metadaten unvollstÃ¤ndig")

    logging.info("Suche Lyrics: %s - %s", track.artist, track.title)
    lyrics = find_lyrics(session, track)
    if not lyrics:
        return FileResult(str(path), "not_found", "Keine Lyrics bei LRCLIB gefunden")

    synced = str(lyrics.get("syncedLyrics") or "").strip()
    plain = str(lyrics.get("plainLyrics") or "").strip()
    source_id = lyrics.get("id")

    if synced:
        lrc_content = ensure_lrc_header(synced, track)
        is_synced = True
    elif plain and config.write_plain_as_lrc and not config.require_synced_lyrics:
        lrc_content = plain_to_lrc(plain, track)
        is_synced = False
    elif plain and config.require_synced_lyrics:
        return FileResult(str(path), "skipped", "Nur unsynchronisierte Lyrics gefunden", source_id=source_id, synced=False)
    else:
        return FileResult(str(path), "not_found", "Kein nutzbarer Lyrics-Inhalt gefunden", source_id=source_id)

    written_lrc_path: Path | None = None
    if config.write_sidecar_lrc:
        written_lrc_path = write_sidecar_lrc(path, lrc_content, config)

    if config.write_embedded_tags:
        write_embedded_tags(path, plain or lrc_content, synced, config)

    if config.touch_audio_on_write and not config.dry_run:
        now = time.time()
        os.utime(path, (now, now))

    return FileResult(
        path=str(path),
        status="written" if not config.dry_run else "dry_run",
        message="Synchronisierte LRC geschrieben" if is_synced else "Unsynchronisierte Lyrics als LRC geschrieben",
        lrc_path=str(written_lrc_path) if written_lrc_path else None,
        source_id=int(source_id) if isinstance(source_id, int) else None,
        synced=is_synced,
    )


def save_report(config: Config, started_at: float, results: list[FileResult]) -> None:
    if not config.save_report:
        return
    report = {
        "app": APP_NAME,
        "version": APP_VERSION,
        "copyright": SCRIPT_COPYRIGHT,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started_at)),
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "music_dir": str(config.music_dir),
        "summary": {
            "total": len(results),
            "written": sum(1 for item in results if item.status == "written"),
            "dry_run": sum(1 for item in results if item.status == "dry_run"),
            "skipped": sum(1 for item in results if item.status == "skipped"),
            "not_found": sum(1 for item in results if item.status == "not_found"),
            "error": sum(1 for item in results if item.status == "error"),
        },
        "results": [asdict(result) for result in results],
    }
    if config.dry_run:
        logging.info("DRY_RUN: WÃ¼rde Bericht speichern: %s", config.report_path)
        return
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("Bericht gespeichert: %s", config.report_path)


def run_once(config: Config) -> int:
    if not config.music_dir.exists():
        logging.error("Musikordner existiert nicht: %s", config.music_dir)
        return 2

    started_at = time.time()
    session = requests.Session()
    session.headers.update({"User-Agent": config.user_agent, "Accept": "application/json"})

    results: list[FileResult] = []
    processed = 0

    logging.info("%s %s gestartet", APP_NAME, APP_VERSION)
    logging.info(SCRIPT_COPYRIGHT)
    logging.info("Musikordner: %s", config.music_dir)
    logging.info("Erweiterungen: %s", ", ".join(sorted(config.audio_extensions)))

    for path in iter_audio_files(config.music_dir, config.audio_extensions):
        if config.max_files_per_run > 0 and processed >= config.max_files_per_run:
            logging.info("MAX_FILES_PER_RUN erreicht: %s", config.max_files_per_run)
            break
        processed += 1
        try:
            result = process_file(path, session, config)
        except Exception as exc:
            logging.exception("Fehler bei Datei: %s", path)
            result = FileResult(str(path), "error", str(exc))
        results.append(result)
        logging.info("%s: %s - %s", result.status.upper(), path, result.message)
        if config.request_delay_seconds > 0:
            time.sleep(config.request_delay_seconds)

    save_report(config, started_at, results)
    written = sum(1 for item in results if item.status in {"written", "dry_run"})
    errors = sum(1 for item in results if item.status == "error")
    logging.info("Fertig. Dateien geprÃ¼ft: %s, geschrieben: %s, Fehler: %s", len(results), written, errors)
    return 1 if errors else 0


def main() -> int:
    config = load_config()
    configure_logging(config.log_level)

    if config.scan_interval_seconds <= 0:
        return run_once(config)

    exit_code = 0
    while True:
        exit_code = run_once(config)
        logging.info("NÃ¤chster Scan in %s Sekunden", config.scan_interval_seconds)
        time.sleep(config.scan_interval_seconds)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
