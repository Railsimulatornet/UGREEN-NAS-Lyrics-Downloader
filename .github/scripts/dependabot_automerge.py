#!/usr/bin/env python3
"""Fail-closed Dependabot patch merger; executes trusted default-branch code only."""
import argparse
import base64
import fnmatch
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

OWNER = 'Railsimulatornet'
CONFIG = {
    'autoheal': {
        'codeql': ('Analyze (actions)', 'Analyze (python)'),
        'pipeline': 'Docker Image',
        'jobs': ('metadata', 'security / security', 'validate'),
        'dispatch': 'docker-publish.yml',
        'docker': ('Dockerfile',),
    },
    'schulmanager-homework-watcher': {
        'codeql': ('Analyze (actions)', 'Analyze (javascript-typescript)'),
        'pipeline': 'Container security scan',
        'jobs': ('build', 'trivy (amd64, ubuntu-24.04)', 'trivy (arm64, ubuntu-24.04-arm)'),
        'dispatch': 'security-scan.yml',
        'npm': ('package.json', 'package-lock.json', 'npm-shrinkwrap.json'),
    },
    'UGREEN-NAS-Lyrics-Downloader': {
        'codeql': ('Analyze (actions)', 'Analyze (python)'),
        'pipeline': 'Build and publish Docker image',
        'jobs': ('metadata', 'security / trivy'),
        'dispatch': 'docker-publish.yml',
        'docker': ('UGREEN-NAS-Lyrics-Downloader/Dockerfile',),
        'pip': ('UGREEN-NAS-Lyrics-Downloader/requirements.txt',
                'UGREEN-NAS-Lyrics-Downloader/requirements-*.txt',
                'UGREEN-NAS-Lyrics-Downloader/pyproject.toml',
                'UGREEN-NAS-Lyrics-Downloader/poetry.lock'),
    },
    'UGREEN-NAS-Syncthing-Reporter': {
        'codeql': ('Analyze (actions)', 'Analyze (python)'),
        'pipeline': 'Build and publish Syncthing Reporter image',
        'jobs': ('build-scan',),
        'dispatch': 'docker-publish.yml',
        'docker': ('syncthing/syncthing_reporter_py/Dockerfile',),
        'pip': ('syncthing/syncthing_reporter_py/requirements.txt',
                'syncthing/syncthing_reporter_py/requirements-*.txt',
                'syncthing/syncthing_reporter_py/pyproject.toml',
                'syncthing/syncthing_reporter_py/poetry.lock'),
    },
}
PATCH_LABELS = {
    'automerge:patch:github-actions': 'github-actions',
    'automerge:patch:docker': 'docker',
    'automerge:patch:npm': 'npm',
    'automerge:patch:pip': 'pip',
}
CODEQL_PATHS = (
    '.github/workflows/codeql.yml',
    '.github/workflows/security-scan.yml',
    '.github/workflows/docker-publish.yml',
)
ACTION_RE = re.compile(r'^\s*uses:\s*github/codeql-action/(init|analyze|upload-sarif)@'
                       r'([0-9a-f]{40}|v[0-9]+\.[0-9]+\.[0-9]+)(?:\s+#.*)?\s*$')
UPLOAD_RE = re.compile(r'uses:\s*github/codeql-action/upload-sarif@'
                       r'([0-9a-f]{40}|v[0-9]+\.[0-9]+\.[0-9]+)')
SKIPPED_CHECKS = {'publish', 'release', 'merge'}


class Blocked(Exception):
    """Expected safety gate; never merge."""


class GitHubAPI:
    def __init__(self, repo, token):
        self.repo = repo
        self.token = token

    def request(self, route, method='GET', payload=None):
        url = 'https://api.github.com' + route
        headers = {'Accept': 'application/vnd.github+json',
                   'Authorization': 'Bearer ' + self.token,
                   'X-GitHub-Api-Version': '2022-11-28',
                   'User-Agent': 'dependabot-patch-automerge-v1'}
        body = json.dumps(payload).encode() if payload is not None else None
        req = Request(url, headers=headers, data=body, method=method)
        try:
            with urlopen(req, timeout=25) as response:
                content = response.read()
                return json.loads(content) if content else None
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f'GitHub {method} {route}: {exc}') from exc

    def get(self, route):
        return self.request(route)

    def pages(self, route, key=None):
        entries = []
        for page in range(1, 11):  # Fail closed rather than silently ignore overflow.
            delimiter = '&' if '?' in route else '?'
            data = self.get(f'{route}{delimiter}per_page=100&page={page}')
            chunk = data[key] if key else data
            if not isinstance(chunk, list):
                raise RuntimeError(f'Unexpected GitHub API page at {route}')
            entries.extend(chunk)
            if len(chunk) < 100:
                return entries
        raise RuntimeError(f'Pagination exceeded safe limit: {route}')

    def file(self, path, ref):
        encoded = quote(path, safe='/')
        data = self.get(f'/repos/{self.repo}/contents/{encoded}?ref={quote(ref)}')
        if data.get('encoding') != 'base64':
            raise Blocked(f'Unexpected file encoding: {path}')
        return base64.b64decode(data['content']).decode('utf-8')


def patch_family(pr):
    labels = {x['name'] for x in pr['labels']}
    families = [family for label, family in PATCH_LABELS.items() if label in labels]
    if len(families) != 1:
        raise Blocked('No unambiguous Dependabot patch classification')
    return families[0]


def check_codeql_patch(files):
    """Reject workflow edits unless each changed line is one CodeQL action pin."""
    changed = []
    for file in files:
        if file['filename'] not in CODEQL_PATHS or file['status'] != 'modified':
            raise Blocked('CodeQL patch changes unexpected file')
        patch = file.get('patch')
        if not patch:
            raise Blocked('Unavailable diff for CodeQL patch')
        removed, added = [], []
        for line in patch.splitlines():
            if line.startswith(('+++', '---')) or not line.startswith(('+', '-')):
                continue
            match = ACTION_RE.fullmatch(line[1:])
            if not match:
                raise Blocked('CodeQL patch modifies more than action references')
            (removed if line[0] == '-' else added).append(match.groups())
        if not removed or len(removed) != len(added):
            raise Blocked('Unexpected CodeQL action diff')
        for (old_action, old_ref), (new_action, new_ref) in zip(removed, added):
            if old_action != new_action or old_ref == new_ref:
                raise Blocked('CodeQL component mismatch or unchanged ref')
            if old_ref.startswith('v') != new_ref.startswith('v'):
                raise Blocked('CodeQL ref pin format changed')
            if old_ref.startswith('v'):
                before = tuple(map(int, old_ref[1:].split('.')))
                after = tuple(map(int, new_ref[1:].split('.')))
                if before[:2] != after[:2] or after[2] <= before[2]:
                    raise Blocked('CodeQL version is not a patch update')
            changed.append(new_action)
    if not changed or len(changed) > 10:
        raise Blocked('No bounded CodeQL patch')
    return 'upload-sarif' in changed


def eligible_files(family, files, config):
    if not files:
        raise Blocked('No changed files')
    if family == 'github-actions':
        return check_codeql_patch(files)
    allowed = config.get(family, ())
    if not allowed or any(f['status'] != 'modified' or not any(
            fnmatch.fnmatchcase(f['filename'], p) for p in allowed) for f in files):
        raise Blocked(f'Unexpected files in {family} patch')
    return True  # Running the container pipeline is mandatory.


def tag_sha(api, tag, cache):
    if tag in cache:
        return cache[tag]
    data = api.get('/repos/github/codeql-action/git/ref/tags/' + tag)
    obj = data['object']
    for _ in range(3):
        if obj['type'] == 'commit':
            cache[tag] = obj['sha']
            return obj['sha']
        if obj['type'] != 'tag':
            break
        obj = api.get('/repos/github/codeql-action/git/tags/' + obj['sha'])['object']
    raise Blocked('Cannot resolve immutable CodeQL release tag ' + tag)


def enforce_codeql_alignment(api, sha):
    """All CodeQL init, analyze and SARIF references must resolve to one commit."""
    codeql = api.file('.github/workflows/codeql.yml', sha)
    init_refs = re.findall(r'uses:\s*github/codeql-action/init@([0-9a-f]{40}|v\d+\.\d+\.\d+)', codeql)
    analyze_refs = re.findall(r'uses:\s*github/codeql-action/analyze@([0-9a-f]{40}|v\d+\.\d+\.\d+)', codeql)
    if len(init_refs) != 1 or len(analyze_refs) != 1 or init_refs[0] != analyze_refs[0]:
        raise Blocked('CodeQL init/analyze versions differ')
    refs = init_refs + analyze_refs
    for path in ('.github/workflows/security-scan.yml', '.github/workflows/docker-publish.yml'):
        try:
            data = api.file(path, sha)
        except RuntimeError as err:
            # Files expected to exist in these four repositories. An unknown
            # read failure cannot be treated as an absent uploader.
            if '404' not in str(err):
                raise
            continue
        refs.extend(UPLOAD_RE.findall(data))
    if len(refs) < 3:
        raise Blocked('No SARIF upload action found for alignment check')
    cache = {}
    immutable = {tag_sha(api, v, cache) if v.startswith('v') else v for v in refs}
    if len(immutable) != 1:
        raise Blocked('CodeQL init/analyze/upload-sarif versions do not align')


def verify_checks(api, head, config, require_pipeline):
    runs = api.pages(f'/repos/{api.repo}/actions/runs?event=pull_request&head_sha={head}', 'workflow_runs')
    if not runs:
        raise Blocked('No PR workflow runs found')
    if any(run['status'] != 'completed' or run.get('conclusion') != 'success'
           for run in runs):
        raise Blocked('PR workflow run pending or unsuccessful')
    names = {run['name'] for run in runs}
    expected = {'CodeQL'} | ({config['pipeline']} if require_pipeline else set())
    if not expected.issubset(names):
        raise Blocked('Expected workflows missing: ' + ', '.join(sorted(expected - names)))

    checks = api.pages(f'/repos/{api.repo}/commits/{head}/check-runs', 'check_runs')
    if not checks:
        raise Blocked('No check runs found')
    successes = {c['name'] for c in checks if c['status'] == 'completed' and c.get('conclusion') == 'success'}
    required = {'CodeQL', *config['codeql']} | (set(config['jobs']) if require_pipeline else set())
    if not required.issubset(successes):
        raise Blocked('Expected successful checks missing: ' + ', '.join(sorted(required - successes)))
    for check in checks:
        if check['status'] != 'completed':
            raise Blocked(f"Check pending: {check['name']}")
        conclusion = check.get('conclusion')
        if conclusion == 'success' or (conclusion == 'skipped' and check['name'] in SKIPPED_CHECKS):
            continue
        raise Blocked(f"Unsuccessful/non-verifiable check: {check['name']} ({conclusion})")

    statuses = api.get(f'/repos/{api.repo}/commits/{head}/status').get('statuses', [])
    if any(s.get('state') != 'success' for s in statuses):
        raise Blocked('Pending/failing legacy commit status')


def verify_candidate(api, number, config, event_sha=None):
    repo = api.repo
    pr = api.get(f'/repos/{repo}/pulls/{int(number)}')
    if pr.get('state') != 'open' or pr.get('draft') or pr.get('user', {}).get('login') != 'dependabot[bot]':
        raise Blocked('Not an open Dependabot PR')
    if pr.get('base', {}).get('ref') != 'main' or pr.get('head', {}).get('repo', {}).get('full_name') != repo:
        raise Blocked('Unexpected branch or head repository')
    if not pr.get('head', {}).get('ref', '').startswith('dependabot/'):
        raise Blocked('Unexpected Dependabot branch name')
    sha = pr['head']['sha']
    if event_sha and sha != event_sha:
        raise Blocked('Trigger belongs to an older commit')
    family = patch_family(pr)
    files = api.pages(f'/repos/{repo}/pulls/{int(number)}/files')
    require_pipeline = eligible_files(family, files, config)
    if family == 'github-actions':
        enforce_codeql_alignment(api, sha)
    main = api.get(f'/repos/{repo}/git/ref/heads/main')['object']['sha']
    if pr['base']['sha'] != main:
        raise Blocked('PR base snapshot is stale')
    cmp = api.get(f'/repos/{repo}/compare/{main}...{sha}')
    if cmp.get('behind_by') != 0 or not cmp.get('ahead_by', 0):
        raise Blocked('Dependabot branch needs rebase onto current main')
    if pr.get('mergeable') is not True or pr.get('mergeable_state') not in ('clean', 'unstable'):
        raise Blocked('PR not proven mergeable')
    verify_checks(api, sha, config, require_pipeline)
    return sha, family


def merge_candidate(api, number, config, dry_run, event_sha=None):
    sha, family = verify_candidate(api, number, config, event_sha)
    if dry_run:
        print(f'PASS DRY-RUN #{number}: verified {sha}, family={family}')
        return
    current = api.get(f'/repos/{api.repo}/git/ref/heads/main')['object']['sha']
    pr = api.get(f'/repos/{api.repo}/pulls/{int(number)}')
    if pr['head']['sha'] != sha or pr['base']['sha'] != current:
        raise Blocked('PR/base moved before merge')
    result = api.request(f'/repos/{api.repo}/pulls/{int(number)}/merge', 'PUT',
                         {'sha': sha, 'merge_method': 'squash'})
    if not result or not result.get('merged'):
        raise RuntimeError('GitHub did not confirm merge')
    print(f'MERGED #{number}: {result["sha"]} ({family})')
    # Explicit dispatch: GITHUB_TOKEN merges do not fire push-triggered workflows.
    # Never dispatch a publication workflow for a CI-only CodeQL update.
    workflow = 'codeql.yml' if family == 'github-actions' else config['dispatch']
    api.request(f'/repos/{api.repo}/actions/workflows/{workflow}/dispatches', 'POST', {'ref': 'main'})
    print(f'DISPATCHED post-merge {workflow} on main')


def choose_prs(api, event):
    kind = event.get('event_type', '')
    if kind == 'workflow_run':
        data = event.get('workflow_run', {})
        if data.get('event') != 'pull_request' or data.get('actor', {}).get('login') != 'dependabot[bot]':
            return [], None
        numbers = [pr['number'] for pr in data.get('pull_requests', [])]
        return sorted(set(numbers)), data.get('head_sha')
    if kind in ('schedule', 'workflow_dispatch'):
        prs = api.pages(f'/repos/{api.repo}/pulls?state=open')
        return [p['number'] for p in prs if p.get('user', {}).get('login') == 'dependabot[bot]'], None
    return [], None


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--dry-run', action='store_true')
    args = cli.parse_args()
    repo = os.environ['GITHUB_REPOSITORY']
    if not repo.startswith(OWNER + '/') or repo.split('/', 1)[1] not in CONFIG:
        raise SystemExit('Repository is not allowlisted')
    token = os.environ['GH_TOKEN']
    api = GitHubAPI(repo, token)
    with open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8') as fh:
        event = json.load(fh)
    event['event_type'] = os.environ['GITHUB_EVENT_NAME']
    numbers, event_sha = choose_prs(api, event)
    if not numbers:
        print('No eligible Dependabot PRs in this event')
    for number in numbers:
        try:
            merge_candidate(api, number, CONFIG[repo.split('/', 1)[1]], args.dry_run, event_sha)
        except Blocked as exc:
            print(f'BLOCKED #{number}: {exc}')
        # Deliberately fail job on GitHub API/dispatch errors instead of hiding them.


if __name__ == '__main__':
    main()
