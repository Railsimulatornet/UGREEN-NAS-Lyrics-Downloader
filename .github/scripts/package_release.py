"""Build a release using the verified previous package as a layout template."""
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from release_metadata import REPOSITORY, validate_version

PREVIOUS_ZIP = 'UGREEN-NAS-Lyrics-Downloader_V1.0.1.zip'
MANUAL = 'UGREEN_NAS_Lyrics_Downloader_Handbuch_DE-EN.pdf'
EXPECTED = {PREVIOUS_ZIP: 'af1cf9271656e8c6e2e97eaf918d5ccec23840f3326dc63e110f9c1c99c75efb',
            MANUAL: 'f312b35222a250f5484bf3331879959406e6abb2f6f3e05007e33b94fdf3adad'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_package(previous, manual, output, version):
    source = Path('UGREEN-NAS-Lyrics-Downloader')
    validate_version(version)
    if sha(previous) != EXPECTED[PREVIOUS_ZIP] or sha(manual) != EXPECTED[MANUAL]:
        raise ValueError('Previous release asset checksum mismatch')
    with zipfile.ZipFile(previous) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != len(set(names)) or len(entries) > 200 or sum(e.file_size for e in entries) > 50_000_000:
            raise ValueError('Unexpected release archive structure')
        for entry in entries:
            name = PurePosixPath(entry.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in entry.filename or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError('Unsupported archive entry')
        candidates = [name[:-len('app/lyrics_downloader.py')] for name in names if name.endswith('app/lyrics_downloader.py')]
        if len(candidates) != 1:
            raise ValueError('Unable to identify the previous package root')
        prefix = candidates[0]
        contents = {entry.filename: archive.read(entry) for entry in entries if not entry.is_dir()}
        for name in contents:
            relative = name[len(prefix):] if name.startswith(prefix) else name
            if relative.startswith(('reports/', 'config/')) and not relative.endswith('.gitkeep'):
                raise ValueError('Unexpected state file in release template: ' + relative)
        print('Previous package files:')
        for name in sorted(contents):
            print('  ' + name)
        for relative in ('Dockerfile', 'requirements.txt', 'docker-compose.yaml', 'app/lyrics_downloader.py',
                         '.dockerignore', 'CHANGELOG.md'):
            data = (source / relative).read_bytes()
            if relative == 'app/lyrics_downloader.py':
                text = data.decode('utf-8-sig')
                text, count = re.subn(r'^APP_VERSION = .*$', f'APP_VERSION = "{version}"', text, flags=re.MULTILINE)
                if count != 1:
                    raise ValueError('Application version marker missing')
                data = text.encode('utf-8')
                compile(data, relative, 'exec')
            contents[prefix + relative] = data
        contents[prefix + 'README.md'] = Path('README.md').read_bytes()
        contents[prefix + 'LICENSE'] = Path('LICENSE').read_bytes()
        # Only ship the repository's example configuration, never local state.
        sample = (source / '.env.example').read_bytes()
        contents[prefix + '.env.example'] = sample
        if prefix + '.env' in contents:
            contents[prefix + '.env'] = sample
        for name in list(contents):
            if PurePosixPath(name).name == MANUAL:
                contents[name] = manual.read_bytes()
        contents[prefix + 'VERSION'] = (version + '\n').encode()
        output.mkdir(parents=True, exist_ok=True)
        target = output / f'UGREEN-NAS-Lyrics-Downloader_V{version}.zip'
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as result:
            for entry in entries:
                if entry.is_dir():
                    result.writestr(entry, b'')
            for name, data in sorted(contents.items()):
                result.writestr(name, data)
        with zipfile.ZipFile(target) as result:
            if result.testzip() is not None or not set(names).issubset(result.namelist()):
                raise ValueError('Release archive validation failed')
            for relative in ('Dockerfile', 'requirements.txt', 'docker-compose.yaml'):
                if result.read(prefix + relative) != (source / relative).read_bytes():
                    raise ValueError('Package does not match repository: ' + relative)
        shutil.copyfile(manual, output / MANUAL)
        (output / 'SHA256SUMS.txt').write_text(''.join(f'{sha(p)}  {p.name}\n' for p in (target, output / MANUAL)), encoding='utf-8')
        print('Package structure preserved; current sources included; manual unchanged.')
        return target


def main():
    output = Path(sys.argv[1]).resolve()
    version = validate_version(Path('VERSION').read_text().strip())
    with tempfile.TemporaryDirectory(prefix='lyrics-release-baseline-') as tmp:
        command = ['gh', 'release', 'download', 'v1.0.1', '--repo', REPOSITORY, '--dir', tmp]
        for name in EXPECTED:
            command += ['--pattern', name]
        subprocess.run(command, check=True, timeout=120)
        build_package(Path(tmp) / PREVIOUS_ZIP, Path(tmp) / MANUAL, output, version)


if __name__ == '__main__':
    main()
