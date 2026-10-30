#!/usr/bin/env python3
"""Build the explicit code-only Mac verification addon without downloads.

The existing reviewed helper supplies Node and the Darwin native adapter. No
browser profiles, private copies, credentials or recursively discovered files
are input to this builder. Native owner-Mac acceptance remains pending.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/private_verify'
BOOTSTRAP = 'mac-bootstrap.cjs'
LAUNCHER = 'Start Mac verification.command'
APP = ('core.cjs', 'mac-main.cjs', 'owner-export.cjs', 'owner-export.sql',
       'local-restore.cjs', 'sql-sources.json', 'pglite/index.cjs',
       'pglite/pglite.wasm', 'pglite/pglite.data', 'pglite/package.json',
       'pglite/LICENSE')
MAX_FILE = 160 * 1024 * 1024
OLD_MANIFEST_SHA256 = '5136a4d4a3c864f6643b00322bab2405b6a4efd904f169a46a9394f442f422b4'
NODE_PINS = {
    'arm64': '2cc28a1880d0774616959f2210ee739bffa6ac695c887e8988a496a21271f6c0',
    'x64': 'e55a748c81980fda1399e65b686708960d6bb9b7e8ea5913d85a97c6a19e7a7b',
}
ASSET_PINS = {
    'sql-sources.json': ('abe00a55653213df3a162cec4387ec1224dd216790114c8da40cb19d2be243ba', 21779),
    'pglite/index.cjs': ('37ba5965b7042f78b128eaed205ad076153e32468efb2796ddf706feb25e4e06', 408401),
    'pglite/pglite.wasm': ('8140392c5f70c5aecb40f514db242fce4223cfdd5f37a2b101dbdc30208dc49d', 8859436),
    'pglite/pglite.data': ('4703ec26f5710abb62db42acad229478b75c51ef7f3bb037286bb2bac139a930', 4939155),
    'pglite/package.json': ('a540c379fd1d820810793681d25fa7ad5dadfcee2b190d14a6553fdb469cfe3c', 5853),
    'pglite/LICENSE': ('a6cba85bc92e0cff7a450b1d873c0eaa2e9fc96bf472df0247a26bec77bf3ff9', 10173),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> bool:
    return (isinstance(name, str) and 0 < len(name) <= 500
            and re.fullmatch(r'[A-Za-z0-9@._ +/()-]+', name) is not None
            and not name.startswith('/')
            and all(piece and piece not in ('.', '..') for piece in name.split('/')))


def no_link_ancestors(path: Path) -> None:
    absolute = path.absolute()
    if any(piece in ('.', '..') for piece in path.parts):
        raise ValueError('unsafe program path')
    for ancestor in (absolute, *absolute.parents):
        if ancestor.is_symlink():
            raise ValueError('program path link forbidden')


def regular_bytes(path: Path) -> bytes:
    no_link_ancestors(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 <= before.st_size <= MAX_FILE):
            raise ValueError('unsafe or oversized program input')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(MAX_FILE + 1)
        after = os.fstat(descriptor)
        current = path.lstat()
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
                                 item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current) or len(data) != before.st_size:
            raise ValueError('program input changed')
        return data
    finally:
        os.close(descriptor)


def encoded(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf8')


def replace_once(data: bytes, marker: bytes, replacement: str) -> bytes:
    if data.count(marker) != 1 or re.fullmatch('[a-f0-9]{64}', replacement) is None:
        raise ValueError('invalid bootstrap trust marker')
    return data.replace(marker, replacement.encode('ascii'))


def build(*, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new ZIP')
    no_link_ancestors(output)
    files = {}
    for name in APP:
        if not safe_name(name):
            raise ValueError('invalid source allowlist')
        data = regular_bytes(SOURCE.joinpath(*name.split('/')))
        if name in ASSET_PINS and (sha(data), len(data)) != ASSET_PINS[name]:
            raise ValueError('pinned restore asset mismatch')
        files['app/' + name] = data
    files['README_MAC_RU.txt'] = regular_bytes(SOURCE / 'README_MAC_RU.txt')
    bootstrap = regular_bytes(SOURCE / BOOTSTRAP)
    launcher = regular_bytes(SOURCE / LAUNCHER)
    if (OLD_MANIFEST_SHA256.encode() not in bootstrap
            or any(value.encode() not in bootstrap or value.encode() not in launcher for value in NODE_PINS.values())):
        raise ValueError('original helper trust pins missing')
    files['BUILD.json'] = encoded({
        'format': 'marichevy-private-verification-macos-build-v1',
        'target': 'darwin-universal-addon', 'contains_private_data': False,
        'existing_helper_manifest_sha256': OLD_MANIFEST_SHA256,
        'existing_runtime': {'version': 'v22.23.4', 'sha256': NODE_PINS},
        'native_macos_acceptance': 'pending-owner-device-check',
        'restore_scope': 'offline-four-app-tables-auth-id-stubs',
        'restore_engine': 'pglite-0.3.14-postgresql-17.5-wasm-in-memory',
        'supabase_auth_or_platform_restored': False,
        'server_concurrency_tested_by_this_addon': False,
        'sources': {name: sha(data) for name, data in sorted(files.items())},
        'bootstrap_template_sha256': sha(bootstrap),
        'launcher_template_sha256': sha(launcher),
    })
    manifest = encoded({'format': 'marichevy-private-verification-macos-bundle-v1',
                        'files': [{'path': name, 'bytes': len(data), 'sha256': sha(data)}
                                  for name, data in sorted(files.items())]})
    generated_bootstrap = replace_once(bootstrap, b'__ADDON_MANIFEST_SHA256__', sha(manifest))
    generated_launcher = replace_once(launcher, b'__ADDON_BOOTSTRAP_SHA256__', sha(generated_bootstrap))
    files.update({'MANIFEST.json': manifest, 'app/' + BOOTSTRAP: generated_bootstrap,
                  LAUNCHER: generated_launcher})
    if (any(not safe_name(name) for name in files)
            or len({name.casefold() for name in files}) != len(files)
            or any(name.startswith('PRIVATE') for name in files)):
        raise ValueError('unsafe archive inventory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        try:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name, data in sorted(files.items()):
                    item = zipfile.ZipInfo(name, (2026, 10, 27, 0, 0, 0))
                    item.create_system = 3
                    item.external_attr = (0o100755 if name == LAUNCHER else 0o100644) << 16
                    archive.writestr(item, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        except BaseException:
            stream.close()
            output.unlink(missing_ok=True)
            raise
    with zipfile.ZipFile(output) as archive:
        if sorted(archive.namelist()) != sorted(files) or archive.testzip() is not None:
            raise ValueError('archive verification failed')
        for name, data in files.items():
            if archive.read(name) != data:
                raise ValueError('archive content mismatch')
    return {'format': 'marichevy-private-verification-macos-report-v1',
            'outcome': 'built-code-only', 'contains_private_data': False,
            'bytes': output.stat().st_size, 'sha256': sha(output.read_bytes()),
            'file_count': len(files), 'manifest_sha256': sha(manifest),
            'bootstrap_sha256': sha(generated_bootstrap),
            'existing_helper_manifest_sha256': OLD_MANIFEST_SHA256,
            'native_owner_mac_acceptance': 'pending',
            'native_owner_mac_passed': False,
            'production_changed': False, 'release_authorized': False,
            'restore_scope': 'offline-four-app-tables-auth-id-stubs',
            'supabase_auth_or_platform_restored': False,
            'server_concurrency_tested_by_this_addon': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    print(json.dumps(build(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == '__main__':
    main()
