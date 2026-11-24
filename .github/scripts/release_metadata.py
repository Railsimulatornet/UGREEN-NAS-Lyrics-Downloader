"""Validated release and maintenance tags for the Lyrics Downloader."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = 'Railsimulatornet/UGREEN-NAS-Lyrics-Downloader'
VERSION_PATTERN = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
COMMIT_PATTERN = r'[a-f0-9]{40}'


def changed_paths(before, after, expected_head, *, cwd=None):
    """Read the complete immutable push diff; unknown history cannot publish."""
    if (not all(isinstance(ref, str) and re.fullmatch(COMMIT_PATTERN, ref)
                and ref != '0' * 40 for ref in (before, after, expected_head))
            or after != expected_head):
        raise ValueError('A push requires its exact before and after commits')
    head = subprocess.run(['git', 'rev-parse', '--verify', 'HEAD'], cwd=cwd,
                          check=True, capture_output=True, text=True, timeout=30)
    if head.stdout.strip() != expected_head:
        raise ValueError('Checked-out source differs from the push commit')
    kind = subprocess.run(['git', 'cat-file', '-t', before], cwd=cwd,
                          check=True, capture_output=True, text=True, timeout=30)
    if kind.stdout.strip() != 'commit':
        raise ValueError('The push base is not a commit')
    diff = subprocess.run(['git', 'diff', '--no-renames', '--name-only', '-z',
                           before, after, '--'], cwd=cwd, check=True,
                          capture_output=True, text=True, timeout=30)
    if diff.stdout and not diff.stdout.endswith('\0'):
        raise ValueError('Incomplete changed-file list')
    return [path for path in diff.stdout.split('\0') if path]


def has_publication_changes(paths):
    """CI-only maintenance is not shipped; retain other publication behavior."""
    if not isinstance(paths, (list, tuple)):
        raise ValueError('A main push requires its complete changed-file list')
    if any(not isinstance(path, str) or not path or '\0' in path
           or any(part in ('', '.', '..') for part in path.split('/')) for path in paths):
        raise ValueError('Invalid changed-file path')
    return any(not path.startswith('.github/') for path in paths)


def validate_version(value):
    if not re.fullmatch(VERSION_PATTERN, value):
        raise ValueError('VERSION must be a stable X.Y.Z version')
    return value


def make_metadata(version, event, ref, repository, tag_exists, day, run, attempt, paths=None):
    validate_version(version)
    datetime.strptime(day, '%Y%m%d')
    if any(not re.fullmatch(r'[1-9][0-9]*', str(n)) for n in (run, attempt)):
        raise ValueError('Invalid build run or attempt')
    trusted = repository == REPOSITORY
    main_push = trusted and event == 'push' and ref == 'refs/heads/main'
    publish_changes = has_publication_changes(paths) if main_push else True
    release = False
    if trusted and event == 'push':
        if ref.startswith('refs/tags/'):
            if ref != 'refs/tags/v' + version:
                raise ValueError('Git tag does not match VERSION')
            release = True
        elif ref == 'refs/heads/main':
            release = publish_changes and not tag_exists
    publish = trusted and publish_changes and (ref == 'refs/heads/main' or (release and ref == 'refs/tags/v' + version)) and event in ('push', 'schedule', 'workflow_dispatch')
    build = f'{version}-build.{day}.{run}.{attempt}'
    return {'version': version, 'build_version': version if release else build,
            'release': str(release).lower(), 'publish': str(publish).lower(),
            'tag': version if release else build}


def remote_tag_exists(version):
    validate_version(version)
    result = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/git/matching-refs/tags/v{version}'],
                            check=True, capture_output=True, text=True, timeout=30)
    refs = json.loads(result.stdout)
    if not isinstance(refs, list) or any(not isinstance(r, dict) or 'ref' not in r for r in refs):
        raise ValueError('Unexpected Git ref response')
    return any(r['ref'] == 'refs/tags/v' + version for r in refs)


def main():
    version = validate_version(Path('VERSION').read_text().strip())
    env = os.environ
    exists = True
    paths = None
    if (env['GITHUB_REPOSITORY'], env['GITHUB_EVENT_NAME'], env['GITHUB_REF']) == (REPOSITORY, 'push', 'refs/heads/main'):
        event = json.loads(Path(env['GITHUB_EVENT_PATH']).read_text())
        paths = changed_paths(event.get('before'), event.get('after'), env.get('GITHUB_SHA'))
        if has_publication_changes(paths):
            exists = remote_tag_exists(version)
    data = make_metadata(version, env['GITHUB_EVENT_NAME'], env['GITHUB_REF'],
                         env['GITHUB_REPOSITORY'], exists,
                         datetime.now(timezone.utc).strftime('%Y%m%d'),
                         env['GITHUB_RUN_NUMBER'], env['GITHUB_RUN_ATTEMPT'], paths=paths)
    with open(env['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        for key, value in data.items():
            output.write(f'{key}={value}\n')
    print(json.dumps(data, indent=2))


if __name__ == '__main__':
    main()
