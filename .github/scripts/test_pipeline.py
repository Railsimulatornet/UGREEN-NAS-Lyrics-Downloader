"""Offline regression tests for version selection and scan failures."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import release_metadata as meta

ROOT = Path(__file__).parent
FAKE_SKOPEO = r'''#!/usr/bin/env python3
import hashlib, json, os, pathlib, sys
args = sys.argv[1:]
mode = os.environ['SCENARIO']
with open(os.environ['SELECTION_CALLS'], 'a') as out: out.write(json.dumps(args) + '\n')
if 'copy' in args:
    if mode == 'selection-error': sys.exit(1)
    arch = args[args.index('--override-arch') + 1]
    if mode == 'wrong-selection': arch = 'amd64' if arch == 'arm64' else 'arm64'
    destination = pathlib.Path(args[-1].removeprefix('oci:'))
    destination.mkdir(parents=True)
    config = json.dumps({'os': 'linux', 'architecture': arch}).encode()
    digest = 'sha256:' + hashlib.sha256(config).hexdigest()
    (destination / 'config.json').write_bytes(config)
    (destination / 'manifest.json').write_text(json.dumps({'schemaVersion': 2, 'config': {'digest': digest}}))
    sys.exit(0)
if args[0] == 'inspect':
    destination = pathlib.Path(args[-1].removeprefix('oci:'))
    if '--raw' in args:
        if mode == 'index-selection': print(json.dumps({'schemaVersion': 2, 'manifests': []}))
        else: print((destination / 'manifest.json').read_text())
    elif '--config' in args: print((destination / 'config.json').read_text())
    else: sys.exit(2)
    sys.exit(0)
sys.exit(2)
'''
FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps(args) + '\n')
mount = next(a for a in args if a.startswith('type=bind,src=') and a.endswith(',dst=/out'))
out = pathlib.Path(mount[len('type=bind,src='):-len(',dst=/out')])
mount = next(a for a in args if a.startswith('type=bind,src=') and a.endswith(',dst=/image,readonly'))
image = pathlib.Path(mount[len('type=bind,src='):-len(',dst=/image,readonly')])
mode = os.environ['SCENARIO']
gate = '--exit-code' in args
convert = 'convert' in args
if mode == 'scan-error' and not gate and not convert: sys.exit(1)
if mode == 'convert-error' and convert: sys.exit(1)
if '--output' in args and mode != 'missing-report' and not (gate and mode == 'missing-gate-report'):
    file = out / pathlib.Path(args[args.index('--output') + 1]).name
    config = json.loads((image / 'config.json').read_text())
    digest = json.loads((image / 'manifest.json').read_text())['config']['digest']
    if mode == 'wrong-scan-architecture': config['architecture'] = 'amd64' if config['architecture'] == 'arm64' else 'arm64'
    if mode == 'wrong-scan-image': digest = 'sha256:' + '0' * 64
    data = {'Metadata': {'OS': {'Family': 'debian'}, 'ImageConfig': config, 'ImageID': digest},
            'Results': [{'Type': 'debian'}, {'Type': 'python-pkg'}]}
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
            skopeo = root / 'skopeo'
            skopeo.write_text(FAKE_SKOPEO)
            skopeo.chmod(0o755)
            image = root / 'image'
            image.mkdir()
            (image / 'index.json').write_text('{}')
            (image / 'oci-layout').write_text('{}')
            # An unselected multi-platform input exposes its first (AMD64) image.
            config = json.dumps({'os': 'linux', 'architecture': 'amd64'}).encode()
            (image / 'config.json').write_bytes(config)
            (image / 'manifest.json').write_text(json.dumps({
                'schemaVersion': 2, 'config': {'digest': 'sha256:' + hashlib.sha256(config).hexdigest()}}))
            calls = root / 'calls'
            env = dict(os.environ, PATH=f'{root}:{os.environ["PATH"]}', CALLS=str(calls),
                       SCENARIO=scenario, TRIVY_CACHE_DIR=str(root / 'cache'),
                       SELECTION_CALLS=str(root / 'selections'))
            run = subprocess.run(['bash', str(ROOT / 'scan-image.sh'), str(image), platform, str(root / 'out')],
                                 env=env, capture_output=True, text=True, timeout=30)
            commands = [json.loads(x) for x in calls.read_text().splitlines()] if calls.exists() else []
            selections = [json.loads(x) for x in (root / 'selections').read_text().splitlines()] if (root / 'selections').exists() else []
            return run, commands, selections

    def test_both_platforms(self):
        for arch in ('amd64', 'arm64'):
            run, calls, selections = self.run_case('clean', 'linux/' + arch)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(len(calls), 4)
            self.assertNotIn('--ignore-unfixed', calls[0])
            self.assertIn('--exit-code', calls[-1])
            self.assertIn('--skip-db-update', calls[-1])
            self.assertFalse(any('/var/run/docker.sock' in str(c) for c in calls))
            copies = [call for call in selections if 'copy' in call]
            self.assertEqual(len(copies), 1)
            self.assertEqual(copies[0][copies[0].index('--override-arch') + 1], arch)
            self.assertEqual(copies[0][copies[0].index('--override-os') + 1], 'linux')
            self.assertIn('--preserve-digests', copies[0])
            self.assertNotIn('--all', copies[0])
            self.assertTrue(copies[0][-2].startswith('oci:'))
            selected = copies[0][-1].removeprefix('oci:')
            self.assertTrue(all('type=bind,src=' + selected + ',dst=/image,readonly' in call for call in calls))

    def test_failed_or_wrong_platform_selection_never_scans(self):
        for scenario in ('selection-error', 'wrong-selection', 'index-selection'):
            for platform in ('linux/amd64', 'linux/arm64'):
                with self.subTest(scenario=scenario, platform=platform):
                    run, calls, _ = self.run_case(scenario, platform)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertEqual(calls, [])

    def test_scanner_must_report_selected_architecture_and_image(self):
        for scenario in ('wrong-scan-architecture', 'wrong-scan-image'):
            for platform in ('linux/amd64', 'linux/arm64'):
                with self.subTest(scenario=scenario, platform=platform):
                    run, calls, _ = self.run_case(scenario, platform)
                    self.assertNotEqual(run.returncode, 0)
                    self.assertEqual(len(calls), 1)

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
