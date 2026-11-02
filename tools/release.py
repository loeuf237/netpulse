#!/usr/bin/env python3
"""Validate release metadata and build an installable, tracked-files-only bundle."""
import argparse
import hashlib
import io
from pathlib import Path
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]


def release_version(root=ROOT, tag=None):
    values = []
    for name, pattern in (
            ('pyproject.toml', r'^version\s*=\s*"([^"]+)"'),
            ('setup.py', r'^\s*version\s*=\s*"([^"]+)"'),
            ('src/netpulse/__init__.py', r'^__version__\s*=\s*"([^"]+)"')):
        match = re.search(pattern, (root / name).read_text(), re.M)
        if not match:
            raise ValueError('Missing version in ' + name)
        values.append(match[1])
    version = values[0]
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or len(set(values)) != 1:
        raise ValueError('Release versions must agree and use major.minor.patch')
    if tag is not None and tag != 'v' + version:
        raise ValueError('Tag must match source version v' + version)
    notes = root / 'releases' / ('v' + version + '.md')
    if not notes.is_file() or not notes.read_text().strip():
        raise ValueError('Missing release notes: ' + str(notes))
    return version


def build_bundle(destination, root=ROOT):
    version = release_version(root)
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    required = {'bin/netpulse-ctl', 'bin/netpulse-gui', 'bin/netpulse-monitor',
                'bin/tun2socks', 'install.sh', 'uninstall.sh', 'README.md',
                'desktop/netpulse.desktop', 'systemd/netpulse-monitor.service', 'LICENSE'}
    if not required.issubset(names):
        raise ValueError('Installable bundle is missing required tracked files')
    target = destination / ('netpulse-' + version + '-linux-x86_64.tar.gz')
    with tarfile.open(target, 'w:gz') as archive:
        for name in sorted(filter(None, names)):
            if name.startswith(('.github/', 'tests/')) or name in ('.gitignore',):
                continue
            path = root / name
            if path.is_symlink() or not path.is_file():
                raise ValueError('Unexpected tracked path: ' + name)
            data = path.read_bytes()
            info = tarfile.TarInfo('netpulse-' + version + '/' + name)
            info.size = len(data)
            info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            archive.addfile(info, io.BytesIO(data))
    return target


def checksums(destination):
    destination = Path(destination)
    files = sorted(p for p in destination.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
    if not files:
        raise ValueError('No release artifacts to checksum')
    text = ''.join(hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in files)
    (destination / 'SHA256SUMS').write_text(text)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tag')
    parser.add_argument('--dist', type=Path)
    args = parser.parse_args()
    version = release_version(tag=args.tag)
    if args.dist:
        print(build_bundle(args.dist))
        checksums(args.dist)
    print('Release metadata verified: v' + version)


if __name__ == '__main__':
    main()
