"""Offline runtime checks with synthetic metadata and HTTP responses only."""
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import requests
from mutagen.flac import FLAC
from mutagen.id3 import ID3

SOURCE = Path('/app/lyrics_downloader.py')
spec = importlib.util.spec_from_file_location('lyrics_under_test', SOURCE)
app = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = app
spec.loader.exec_module(app)
TEXT = '[00:01.00]Synthetic test line\n[00:02.00]Second fixture line'


class FixtureAdapter(requests.adapters.BaseAdapter):
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def send(self, request, **kwargs):
        self.calls.append((request, kwargs))
        if not self.responses:
            raise AssertionError('Unexpected HTTP request')
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        status, payload = item
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(payload).encode('utf-8')
        response.headers['Content-Type'] = 'application/json'
        response.url = request.url
        response.request = request
        return response

    def close(self):
        pass


class LyricsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='lyrics-fixture-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.music = self.root / 'music'
        self.music.mkdir()
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = app.load_config()
        self.config.music_dir = self.music
        self.config.report_path = self.root / 'reports' / 'report.json'
        self.config.request_delay_seconds = 0
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('Network access forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.path = self.music / 'Fixture Artist - Fixture Track.flac'
        # Synthetic FLAC metadata, without real music or copyrighted audio.
        packed = (44100 << 44) | (1 << 41) | (15 << 36) | (44100 * 5)
        streaminfo = b'\x00\x10\x00\x10' + b'\x00' * 6 + packed.to_bytes(8, 'big') + b'\x00' * 16
        self.path.write_bytes(b'fLaC\x80\x00\x00\x22' + streaminfo)
        audio = FLAC(self.path)
        audio['title'] = 'Fixture Track'
        audio['artist'] = 'Fixture Artist'
        audio['album'] = 'Fixture Album'
        audio.save()
        self.track = app.read_track_info(self.path)
        self.assertIsNotNone(self.track)

    def session(self, *responses):
        session = requests.Session()
        session.trust_env = False
        adapter = FixtureAdapter(responses)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
        self.addCleanup(session.close)
        return session, adapter

    def payload(self, **changes):
        result = {'id': 7, 'trackName': self.track.title, 'artistName': self.track.artist,
                  'albumName': self.track.album, 'duration': 5,
                  'syncedLyrics': TEXT, 'plainLyrics': 'Synthetic test line'}
        result.update(changes)
        return result

    def test_defaults_and_metadata(self):
        self.assertTrue(self.config.skip_existing_lrc)
        self.assertTrue(self.config.require_synced_lyrics)
        self.assertFalse(self.config.write_embedded_tags)
        self.assertEqual(self.config.scan_interval_seconds, 0)
        self.assertEqual(self.track.title, 'Fixture Track')
        self.assertEqual(self.track.duration, 5)

    def test_environment_parsing(self):
        with patch.dict(os.environ, {'DRY_RUN': 'true', 'REQUEST_DELAY_SECONDS': '1,5',
                                    'SCAN_INTERVAL_SECONDS': '86400', 'MAX_FILES_PER_RUN': 'invalid'}):
            config = app.load_config()
            self.assertTrue(config.dry_run)
            self.assertEqual(config.request_delay_seconds, 1.5)
            self.assertEqual(config.scan_interval_seconds, 86400)
            self.assertEqual(config.max_files_per_run, 0)

    def test_exact_request_and_sidecar_preserve_audio_bytes(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        os.utime(self.path, (100, 100))
        session, adapter = self.session((200, self.payload()))
        result = app.process_file(self.path, session, self.config)
        self.assertEqual(result.status, 'written')
        self.assertTrue(result.synced)
        content = self.path.with_suffix('.lrc').read_text()
        self.assertIn('[ti:Fixture Track]', content)
        self.assertIn(TEXT, content)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertGreater(self.path.stat().st_mtime, 100)
        request, options = adapter.calls[0]
        self.assertEqual(urlparse(request.url).path, '/api/get')
        self.assertEqual(parse_qs(urlparse(request.url).query)['artist_name'], ['Fixture Artist'])
        self.assertEqual(options['timeout'], 30)
        self.assertTrue(options['verify'])

    def test_existing_sidecar_is_untouched(self):
        lrc = self.path.with_suffix('.lrc')
        lrc.write_text('Existing fixture')
        before = self.path.read_bytes()
        session, adapter = self.session()
        self.assertEqual(app.process_file(self.path, session, self.config).status, 'skipped')
        self.assertEqual(lrc.read_text(), 'Existing fixture')
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(adapter.calls, [])

    def test_dry_run_does_not_write(self):
        self.config.dry_run = True
        self.config.write_embedded_tags = True
        before, modified = self.path.read_bytes(), self.path.stat().st_mtime_ns
        session, _ = self.session((200, self.payload()))
        result = app.process_file(self.path, session, self.config)
        app.save_report(self.config, time.time(), [result])
        self.assertEqual(result.status, 'dry_run')
        self.assertFalse(self.path.with_suffix('.lrc').exists())
        self.assertFalse(self.config.report_path.exists())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.path.stat().st_mtime_ns, modified)

    def test_search_fallback(self):
        session, adapter = self.session((404, {}), (200, [self.payload()]))
        self.assertEqual(app.find_lyrics(session, self.track)['id'], 7)
        self.assertEqual(urlparse(adapter.calls[1][0].url).path, '/api/search')

    def test_unrelated_search_result_rejected(self):
        session, _ = self.session((404, {}), (200, [self.payload(trackName='Other', artistName='Other', albumName='', duration=100)]))
        self.assertIsNone(app.find_lyrics(session, self.track))

    def test_timeout_is_handled(self):
        session, adapter = self.session(requests.Timeout('Synthetic timeout'))
        self.assertIsNone(app.find_lyrics(session, self.track))
        self.assertEqual(len(adapter.calls), 1)

    def test_plain_lyrics_require_opt_in(self):
        session, _ = self.session((200, self.payload(syncedLyrics=None)))
        self.assertEqual(app.process_file(self.path, session, self.config).status, 'skipped')
        self.assertFalse(self.path.with_suffix('.lrc').exists())
        self.config.require_synced_lyrics = False
        self.config.write_plain_as_lrc = True
        session, _ = self.session((200, self.payload(syncedLyrics=None)))
        result = app.process_file(self.path, session, self.config)
        self.assertEqual(result.status, 'written')
        self.assertFalse(result.synced)

    def test_embedded_flac_tags(self):
        app.write_embedded_tags(self.path, 'Synthetic text', TEXT, self.config)
        tags = FLAC(self.path)
        self.assertEqual(tags['LYRICS'], ['Synthetic text'])
        self.assertEqual(tags['LYRICS_SYNCED'], [TEXT])
        self.assertEqual(tags['title'], ['Fixture Track'])

    def test_embedded_id3_tags(self):
        path = self.music / 'metadata-only.mp3'
        ID3().save(path)
        app.write_embedded_tags(path, 'Synthetic text', TEXT, self.config)
        self.assertEqual(ID3(path).getall('USLT')[0].text, 'Synthetic text')

    def test_report_schema(self):
        results = [app.FileResult('fixture.flac', value, 'Fixture')
                   for value in ('written', 'skipped', 'error', 'not_found', 'dry_run')]
        app.save_report(self.config, time.time(), results)
        report = json.loads(self.config.report_path.read_text())
        self.assertEqual(report['version'], app.APP_VERSION)
        self.assertEqual(report['summary'], {'total': 5, 'written': 1, 'skipped': 1, 'error': 1, 'not_found': 1, 'dry_run': 1})

    def test_no_touch_option(self):
        self.config.touch_audio_on_write = False
        modified = self.path.stat().st_mtime_ns
        session, _ = self.session((200, self.payload()))
        app.process_file(self.path, session, self.config)
        self.assertEqual(self.path.stat().st_mtime_ns, modified)

    def test_missing_music_directory(self):
        self.config.music_dir = self.root / 'absent'
        self.assertEqual(app.run_once(self.config), 2)

    def test_single_run_entrypoint_empty_directory(self):
        empty = self.root / 'empty'
        empty.mkdir()
        env = dict(os.environ, MUSIC_DIR=str(empty), SCAN_INTERVAL_SECONDS='0',
                   REPORT_PATH=str(self.config.report_path), REQUEST_DELAY_SECONDS='0')
        run = subprocess.run([sys.executable, str(SOURCE)], env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(json.loads(self.config.report_path.read_text())['summary']['total'], 0)


if __name__ == '__main__':
    compile(SOURCE.read_bytes(), str(SOURCE), 'exec')
    assert app.APP_VERSION == os.environ['EXPECTED_BUILD_VERSION']
    for name in ('pip', 'setuptools', 'wheel'):
        assert importlib.util.find_spec(name) is None, 'Unexpected build tooling: ' + name
    for requirement in Path('/app/requirements.txt').read_text(encoding='utf-8-sig').splitlines():
        if requirement and not requirement.startswith('#'):
            name, version = requirement.split('==')
            assert importlib.metadata.version(name) == version
            print(name + '=' + version, flush=True)
    unittest.main(verbosity=2)
