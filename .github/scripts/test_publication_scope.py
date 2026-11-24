"""Exercise publication decisions using real local Git history and the caller."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import release_metadata as meta


RUNTIME = ('autoheal.sh' if meta.REPOSITORY.endswith('/autoheal')
           else 'UGREEN-NAS-Lyrics-Downloader/app/lyrics_downloader.py')
SCRIPT = Path(meta.__file__).resolve()


def metadata(**changes):
    args = dict(version='1.0.1', event='push', ref='refs/heads/main',
                repository=meta.REPOSITORY, tag_exists=False, day='20261124',
                run='42', attempt='1', paths=[RUNTIME])
    args.update(changes)
    return meta.make_metadata(**args)


class ScopeDecisions(unittest.TestCase):
    def test_ci_only_changes_never_publish_or_release(self):
        for paths in [[], ['.github/workflows/docker-publish.yml'],
                      ['.github/scripts/release_metadata.py'],
                      ['.github/scripts/patch_policy.py', '.github/scripts/test_publication_scope.py']]:
            with self.subTest(paths=paths):
                result = metadata(paths=paths)
                self.assertEqual((result['publish'], result['release']), ('false', 'false'))

    def test_runtime_and_mixed_changes_retain_publication(self):
        for paths in [[RUNTIME], [RUNTIME, '.github/scripts/release_metadata.py']]:
            with self.subTest(paths=paths):
                result = metadata(paths=paths)
                self.assertEqual((result['publish'], result['release']), ('true', 'true'))
                existing = metadata(paths=paths, tag_exists=True)
                self.assertEqual((existing['publish'], existing['release']), ('true', 'false'))

    def test_missing_or_invalid_path_data_cannot_publish(self):
        for paths in [None, '.github/scripts/test.py', [''], ['../runtime'], ['/runtime'],
                      ['.github/../runtime'], [None], ['runtime\0hidden']]:
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                metadata(paths=paths)

    def test_manual_schedule_and_tag_behavior_is_unchanged(self):
        for event in ['schedule', 'workflow_dispatch']:
            for paths in [None, ['.github/scripts/release_metadata.py']]:
                with self.subTest(event=event, paths=paths):
                    result = metadata(event=event, paths=paths)
                    self.assertEqual((result['publish'], result['release']), ('true', 'false'))
        tagged = metadata(ref='refs/tags/v1.0.1', paths=None)
        self.assertEqual((tagged['publish'], tagged['release']), ('true', 'true'))
        with self.assertRaises(ValueError):
            metadata(ref='refs/tags/v1.0.2', paths=None)


class ImmutablePushHistory(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '--quiet', '--initial-branch=main')
        self.write('VERSION', '1.0.1\n')
        self.write(RUNTIME, 'initial runtime\n')
        self.base = self.commit()
        self.write(RUNTIME, 'updated runtime\n')
        self.middle = self.commit()
        self.write('.github/scripts/release_metadata.py', 'CI fixture\n')
        self.head = self.commit()

    def git(self, *args):
        return subprocess.run(['git', '-c', 'user.name=Test', '-c',
                               'user.email=test@example.invalid', *args], cwd=self.root,
                              check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self):
        self.git('add', '--all')
        self.git('commit', '--quiet', '-m', 'Fixture')
        return self.git('rev-parse', 'HEAD')

    def paths(self, before, after=None):
        head = after or self.head
        return meta.changed_paths(before, head, head, cwd=self.root)

    def test_complete_push_range_includes_earlier_runtime_commit(self):
        paths = self.paths(self.base)
        self.assertEqual(set(paths), {RUNTIME, '.github/scripts/release_metadata.py'})
        self.assertTrue(meta.has_publication_changes(paths))
        self.assertFalse(meta.has_publication_changes(self.paths(self.middle)))

    def test_ci_rename_and_delete_remain_internal(self):
        before = self.head
        source = self.root / '.github/scripts/release_metadata.py'
        renamed = self.root / '.github/scripts/renamed.py'
        source.rename(renamed)
        self.head = self.commit()
        self.assertFalse(meta.has_publication_changes(self.paths(before)))
        before = self.head
        renamed.unlink()
        self.head = self.commit()
        self.assertFalse(meta.has_publication_changes(self.paths(before)))

    def test_runtime_rename_into_ci_keeps_the_deleted_runtime_input(self):
        before = self.head
        (self.root / RUNTIME).rename(self.root / '.github/scripts/previous-runtime')
        self.head = self.commit()
        paths = self.paths(before)
        self.assertIn(RUNTIME, paths)
        self.assertTrue(meta.has_publication_changes(paths))

    def test_unknown_base_or_foreign_head_fails_closed(self):
        for before in [None, '', 'main', '0' * 40]:
            with self.subTest(before=before), self.assertRaises(ValueError):
                self.paths(before)
        with self.assertRaises(subprocess.CalledProcessError):
            self.paths('f' * 40)
        with self.assertRaises(ValueError):
            self.paths(self.git('rev-parse', 'HEAD^{tree}'))
        with self.assertRaises(ValueError):
            meta.changed_paths(self.base, self.middle, self.head, cwd=self.root)
        with self.assertRaises(ValueError):
            meta.changed_paths(self.base, self.middle, self.middle, cwd=self.root)

    def run_caller(self, before):
        event = self.root / 'event.json'
        event.write_text(json.dumps({'before': before, 'after': self.head}))
        output = self.root / 'output'
        calls = self.root / 'gh-called'
        binary = self.root / 'bin'
        binary.mkdir()
        gh = binary / 'gh'
        gh.write_text('#!/bin/sh\n: > "$PUBLICATION_GH_CALL"\nprintf "[]\\n"\n')
        gh.chmod(0o755)
        env = {'PATH': str(binary) + os.pathsep + os.defpath,
               'GITHUB_REPOSITORY': meta.REPOSITORY, 'GITHUB_EVENT_NAME': 'push',
               'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': self.head,
               'GITHUB_EVENT_PATH': str(event), 'GITHUB_OUTPUT': str(output),
               'GITHUB_RUN_NUMBER': '42', 'GITHUB_RUN_ATTEMPT': '1',
               'PUBLICATION_GH_CALL': str(calls)}
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.root, env=env,
                                capture_output=True, text=True, timeout=15)
        values = dict(line.split('=', 1) for line in output.read_text().splitlines()) if output.exists() else {}
        return result, values, calls.exists()

    def test_real_caller_suppresses_ci_only_without_a_release_lookup(self):
        result, values, called = self.run_caller(self.middle)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((values['publish'], values['release']), ('false', 'false'))
        self.assertFalse(called)

    def test_real_caller_preserves_mixed_publication(self):
        result, values, called = self.run_caller(self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((values['publish'], values['release']), ('true', 'true'))
        self.assertTrue(called)

    def test_real_caller_stops_on_unknown_history(self):
        result, values, called = self.run_caller('f' * 40)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(values, {})
        self.assertFalse(called)


if __name__ == '__main__':
    unittest.main()
