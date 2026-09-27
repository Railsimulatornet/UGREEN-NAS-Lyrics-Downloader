"""Validated release and maintenance tags for the Lyrics Downloader."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

REPOSITORY = 'Railsimulatornet/UGREEN-NAS-Lyrics-Downloader'
VERSION_PATTERN = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def validate_version(value):
    if not re.fullmatch(VERSION_PATTERN, value):
        raise ValueError('VERSION must be a stable X.Y.Z version')
    return value


def make_metadata(version, event, ref, repository, tag_exists, day, run, attempt):
    validate_version(version)
    datetime.strptime(day, '%Y%m%d')
    if any(not re.fullmatch(r'[1-9][0-9]*', str(n)) for n in (run, attempt)):
        raise ValueError('Invalid build run or attempt')
    trusted = repository == REPOSITORY
    release = False
    if trusted and event == 'push':
        if ref.startswith('refs/tags/'):
            if ref != 'refs/tags/v' + version:
                raise ValueError('Git tag does not match VERSION')
            release = True
        elif ref == 'refs/heads/main':
            release = not tag_exists
    publish = trusted and (ref == 'refs/heads/main' or (release and ref == 'refs/tags/v' + version)) and event in ('push', 'schedule', 'workflow_dispatch')
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
    if (env['GITHUB_REPOSITORY'], env['GITHUB_EVENT_NAME'], env['GITHUB_REF']) == (REPOSITORY, 'push', 'refs/heads/main'):
        exists = remote_tag_exists(version)
    data = make_metadata(version, env['GITHUB_EVENT_NAME'], env['GITHUB_REF'],
                         env['GITHUB_REPOSITORY'], exists,
                         datetime.now(timezone.utc).strftime('%Y%m%d'),
                         env['GITHUB_RUN_NUMBER'], env['GITHUB_RUN_ATTEMPT'])
    with open(env['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        for key, value in data.items():
            output.write(f'{key}={value}\n')
    print(json.dumps(data, indent=2))


if __name__ == '__main__':
    main()
