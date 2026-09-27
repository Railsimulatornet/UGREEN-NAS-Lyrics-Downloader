"""Registry error and immutable-tag checks with a simulated image-copy tool."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('publish-image.sh')
FAKE = r'''#!/usr/bin/env python3
import hashlib,json,os,pathlib,sys
a=sys.argv[1:]; mode=os.environ['SCENARIO']; state=pathlib.Path(os.environ['PUSHES'])
with open(os.environ['CALLS'],'a') as f: f.write(json.dumps(a)+'\n')
if a[0]=='login': sys.stdin.read(); sys.exit(0)
if a[0]=='manifest-digest':
    print('sha256:'+hashlib.sha256(pathlib.Path(a[-1]).read_bytes()).hexdigest()); sys.exit(0)
if a[0]=='copy':
    with state.open('a') as f: f.write(a[-1]+'\n')
    sys.exit(0)
if a[0]=='inspect':
    target=a[-1]
    if target.startswith('oci-archive:'): print('fixture-manifest'); sys.exit(0)
    pushed=state.read_text().splitlines() if state.exists() else []
    if target in pushed:
        print('changed' if mode=='corrupt-transfer' else 'fixture-manifest'); sys.exit(0)
    if mode=='auth-error': print('unauthorized',file=sys.stderr); sys.exit(1)
    if mode=='network-error': print('connection timeout',file=sys.stderr); sys.exit(1)
    if mode=='conflicting-version' and 'docker.io/' in target: print('old-manifest'); sys.exit(0)
    if mode=='identical-version': print('fixture-manifest'); sys.exit(0)
    print('manifest unknown',file=sys.stderr); sys.exit(1)
sys.exit(2)
'''


class PublishTests(unittest.TestCase):
    def case(self, scenario, tag='1.0.2'):
        with tempfile.TemporaryDirectory(prefix='lyrics publish ') as tmp:
            root = Path(tmp)
            (root / 'image.tar').write_text('fixture')
            (root / 'skopeo').write_text(FAKE)
            (root / 'skopeo').chmod(0o755)
            env = dict(os.environ, PATH=str(root) + ':' + os.environ['PATH'], SCENARIO=scenario,
                       CALLS=str(root / 'calls'), PUSHES=str(root / 'pushes'),
                       GH_TOKEN='fixture', REGISTRY_USER='fixture',
                       DOCKERHUB_USERNAME='fixture', DOCKERHUB_TOKEN='fixture')
            run = subprocess.run(['bash', str(SCRIPT), str(root / 'image.tar'), tag], env=env,
                                 capture_output=True, text=True, timeout=30)
            calls = [json.loads(x) for x in (root / 'calls').read_text().splitlines()] if (root / 'calls').exists() else []
            return run, calls

    def test_both_fixed_tags_before_latest(self):
        run, calls = self.case('new-version')
        self.assertEqual(run.returncode, 0, run.stderr)
        copies = [c[-1] for c in calls if c[0] == 'copy']
        self.assertEqual(len(copies), 4)
        self.assertTrue(all(c.endswith(':1.0.2') for c in copies[:2]))
        self.assertTrue(all(c.endswith(':latest') for c in copies[2:]))

    def test_existing_identical_is_idempotent(self):
        self.assertEqual(self.case('identical-version')[0].returncode, 0)

    def test_conflict_at_second_registry_blocks_all_writes(self):
        run, calls = self.case('conflicting-version')
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(any(c[0] == 'copy' for c in calls))

    def test_registry_errors_block_all_writes(self):
        for scenario in ('auth-error', 'network-error'):
            run, calls = self.case(scenario)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(any(c[0] == 'copy' for c in calls))

    def test_corrupt_transfer_blocks_latest(self):
        run, calls = self.case('corrupt-transfer')
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse(any(c[0] == 'copy' and c[-1].endswith(':latest') for c in calls))

    def test_invalid_tag_rejected(self):
        self.assertNotEqual(self.case('new-version', 'latest')[0].returncode, 0)


if __name__ == '__main__':
    unittest.main()
