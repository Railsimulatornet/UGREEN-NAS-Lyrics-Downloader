"""Offline regression tests for version selection and scan failures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import release_metadata as meta

ROOT = Path(__file__).parent
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(args) + '\n')
mount = next(a for a in args if a.startswith('type=bind,src=') and a.endswith(',dst=/out'))
out = pathlib.Path(mount[len('type=bind,src='):-len(',dst=/out')])
mode = os.environ['SCENARIO']
gate = '--exit-code' in args
convert = 'convert' in args
if mode == 'scan-error' and not gate and not convert: sys.exit(1)
if mode == 'convert-error' and convert: sys.exit(1)
if '--output' in args and mode != 'missing-report' and not (gate and mode == 'missing-gate-report'):
    file = out / pathlib.Path(args[args.index('--output') + 1]).name
    data = {'Metadata': {'OS': {'Family': 'debian'}}, 'Results': [{'Type': 'debian'}, {'Type': 'python-pkg'}]}
    if mode == 'unknown-os': data['Metadata']['OS']['Family'] = 'unknown'
    if mode == 'missing-python': data['Results'].pop()
    file.write_text(json.dumps(data) if file.suffix == '.json' else 'fixture report\n')
if gate and mode in ('findings', 'eol', 'gate-error'): sys.exit({'findings':42, 'eol':43, 'gate-error':1}[mode])
'''


class MetadataTests(unittest.TestCase):
    def data(self, **changes):
        args = dict(version='1.0.2', event='push', ref='refs/heads/main', repository=meta.REPOSITORY,
                    tag_exists=False, day='20260927', run='10', attempt='1')
        args.update(changes)
        return meta.make_metadata(**args)

    def test_new_release(self):
        self.assertEqual(self.data()['tag'], '1.0.2')
        self.assertEqual(self.data()['release'], 'true')

    def test_existing_release(self):
        self.assertEqual(self.data(tag_exists=True)['tag'], '1.0.2-build.20260927.10.1')

    def test_schedule_only_maintenance(self):
        self.assertEqual(self.data(event='schedule')['release'], 'false')

    def test_manual_only_maintenance(self):
        self.assertEqual(self.data(event='workflow_dispatch')['release'], 'false')

    def test_pr_never_publishes(self):
        self.assertEqual(self.data(event='pull_request', ref='refs/pull/1/merge')['publish'], 'false')

    def test_feature_branch_never_publishes(self):
        self.assertEqual(self.data(ref='refs/heads/feature')['publish'], 'false')

    def test_other_repository_never_publishes(self):
        self.assertEqual(self.data(repository='fixture/fork')['publish'], 'false')

    def test_matching_tag(self):
        self.assertEqual(self.data(ref='refs/tags/v1.0.2')['release'], 'true')

    def test_mismatched_tag(self):
        with self.assertRaises(ValueError): self.data(ref='refs/tags/v1.0.1')

    def test_invalid_version(self):
        for value in ('1.2', '01.0.2', '1.0.2\nBAD=1', 'latest'):
            with self.assertRaises(ValueError): self.data(version=value)

    def test_api_errors_fail_closed(self):
        with patch.object(meta.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'gh')):
            with self.assertRaises(subprocess.CalledProcessError): meta.remote_tag_exists('1.0.2')

    def test_retry_tags_are_unique(self):
        self.assertNotEqual(self.data(tag_exists=True)['tag'], self.data(tag_exists=True, attempt='2')['tag'])


class ScanTests(unittest.TestCase):
    def run_case(self, scenario, platform='linux/amd64'):
        with tempfile.TemporaryDirectory(prefix='lyrics gate ') as tmp:
            root = Path(tmp)
            fake = root / 'docker'
            fake.write_text(FAKE_DOCKER)
            fake.chmod(0o755)
            image = root / 'image'
            image.mkdir()
            (image / 'index.json').write_text('{}')
            (image / 'oci-layout').write_text('{}')
            calls = root / 'calls'
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}', CALLS=str(calls),
                       SCENARIO=scenario, TRIVY_CACHE_DIR=str(root / 'cache'))
            run = subprocess.run(['bash', str(ROOT / 'scan-image.sh'), str(image), platform, str(root / 'out')],
                                 env=env, capture_output=True, text=True, timeout=30)
            commands = [json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []
            return run, commands

    def test_both_platforms(self):
        for arch in ('amd64', 'arm64'):
            run, calls = self.run_case('clean', 'linux/' + arch)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(calls), 4)
            self.assertNotIn('--ignore-unfixed', calls[0])
            self.assertIn('--exit-code', calls[-1])
            self.assertIn('--skip-db-update', calls[-1])
            self.assertFalse(any('/var/run/docker.sock' in str(c) for c in calls))

    def test_errors_and_findings_block(self):
        for scenario, expected in [('scan-error', 1), ('convert-error', 1), ('missing-report', 1),
                                   ('missing-gate-report', 1), ('unknown-os', 1), ('missing-python', 1),
                                   ('findings', 42), ('eol', 43), ('gate-error', 1)]:
            with self.subTest(scenario=scenario):
                self.assertEqual(self.run_case(scenario)[0].returncode, expected)

    def test_unknown_platform_rejected(self):
        self.assertEqual(self.run_case('clean', 'linux/other')[0].returncode, 2)


if __name__ == '__main__':
    unittest.main()
