#!/usr/bin/env python3
"""Build a self-contained, code-only Windows verifier without downloads.

Only the pinned existing Windows helper archive supplies Node and Koffi. The
builder never discovers or reads owner inputs, browser profiles or credentials.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/private_verify'
ORIGINAL_ARCHIVE = ROOT / 'preview/windows-private-backup-helper-v95-r2.zip'
ORIGINAL_SHA256 = '54bf8c5dd72deec6029edde888b05d259d8778548fd70cc28f6449d21c57a0df'
ORIGINAL_MANIFEST_SHA256 = '24bdb927e8ed27565e68dac4bb106d27eff9ef40ec557e349976b26ffcf41ceb'
NODE_SHA256 = 'dccc52de28d8df2ee22d2062424f8c563070d95d8ad70c54c4bf01d590dec14f'
NODE_BYTES = 87034184
BOOTSTRAP = 'windows-bootstrap.cjs'
LAUNCHER = 'Start Windows verification.cmd'
PREFLIGHT = 'Start Windows verification.ps1'
APP = ('core.cjs', 'owner-export.cjs', 'owner-export.sql', 'local-restore.cjs',
       'sql-sources.json', 'windows-main.cjs', 'windows-io.cjs',
       'pglite/index.cjs', 'pglite/pglite.wasm', 'pglite/pglite.data',
       'pglite/package.json', 'pglite/LICENSE')
ORIGINAL_FILES = ('runtime/node.exe', 'runtime/NODE-LICENSE.txt', 'app/windows.cjs',
    'app/node_modules/koffi/package.json', 'app/node_modules/koffi/LICENSE.txt',
    'app/node_modules/koffi/index.cjs', 'app/node_modules/koffi/src/koffi/index.cjs',
    'app/node_modules/koffi/src/koffi/src/static.cjs',
    'app/node_modules/@koromix/koffi-win32-x64/package.json',
    'app/node_modules/@koromix/koffi-win32-x64/README.md',
    'app/node_modules/@koromix/koffi-win32-x64/index.js',
    'app/node_modules/@koromix/koffi-win32-x64/win32_x64/koffi.node')
ASSET_PINS = {
    'sql-sources.json': ('abe00a55653213df3a162cec4387ec1224dd216790114c8da40cb19d2be243ba', 21779),
    'pglite/index.cjs': ('37ba5965b7042f78b128eaed205ad076153e32468efb2796ddf706feb25e4e06', 408401),
    'pglite/pglite.wasm': ('8140392c5f70c5aecb40f514db242fce4223cfdd5f37a2b101dbdc30208dc49d', 8859436),
    'pglite/pglite.data': ('4703ec26f5710abb62db42acad229478b75c51ef7f3bb037286bb2bac139a930', 4939155),
    'pglite/package.json': ('a540c379fd1d820810793681d25fa7ad5dadfcee2b190d14a6553fdb469cfe3c', 5853),
    'pglite/LICENSE': ('a6cba85bc92e0cff7a450b1d873c0eaa2e9fc96bf472df0247a26bec77bf3ff9', 10173),
}
MAX_FILE = 160 * 1024 * 1024
# CMD expands one fixed, short command. The captured source bytes are checked
# before ScriptBlock creation; no execution policy is changed. No owner text
# appears in code or in a shell argument.
PREFLIGHT_LOADER = r"""$ErrorActionPreference = 'Stop'; $launchStream = $null; $launchStage = 'shell'; try {
if ($PSVersionTable.PSVersion.Major -lt 5) { Write-Output 'Result: failed'; Write-Output 'Codes: verification-shell-version-unsupported'; return };
if ($ExecutionContext.SessionState.LanguageMode -ne 'FullLanguage') { Write-Output 'Result: failed'; Write-Output 'Codes: verification-shell-restricted'; return };
$launchStage = 'folder'; $launchRoot = (Get-Location).ProviderPath;
if (-not $launchRoot) { throw 'fixed' };
$launchPath = [IO.Path]::Combine($launchRoot, 'Start Windows verification.ps1');
$launchStage = 'metadata';
$launchItem = Get-Item -LiteralPath $launchPath -Force;
if ($launchItem.PSIsContainer -or ($launchItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $launchItem.Length -le 0 -or $launchItem.Length -gt 1048576) { throw 'fixed' };
$launchStage = 'open';
$launchStream = [IO.File]::Open($launchPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read);
$launchStage = 'read';
$launchBytes = New-Object byte[] $launchStream.Length; $launchOffset = 0;
while ($launchOffset -lt $launchBytes.Length) { $launchRead = $launchStream.Read($launchBytes, $launchOffset, $launchBytes.Length - $launchOffset); if ($launchRead -le 0) { throw 'fixed' }; $launchOffset += $launchRead };
if ($launchStream.ReadByte() -ne -1) { throw 'fixed' };
$launchStage = 'hash';
$launchHash = [Security.Cryptography.SHA256]::Create(); try { $launchActual = ([BitConverter]::ToString($launchHash.ComputeHash($launchBytes))).Replace('-', '').ToLowerInvariant() } finally { $launchHash.Dispose() };
if ($launchActual -cne '__WINDOWS_PREFLIGHT_SHA256__') { throw 'fixed' };
$launchStage = 'utf8';
$launchEncoding = [Text.UTF8Encoding]::new($false, $true);
$launchSource = $launchEncoding.GetString($launchBytes);
$launchStage = 'parse'; $launchScript = [ScriptBlock]::Create($launchSource);
$launchStage = 'invoke'; & $launchScript;
} catch { Write-Output 'Result: failed'; Write-Output ('Codes: verification-launch-loader-' + $launchStage) } finally { if ($null -ne $launchStream) { $launchStream.Dispose() } }
"""


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf8')


def safe_name(value: str) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= 500
            and re.fullmatch(r'[A-Za-z0-9@._ +/()-]+', value) is not None
            and not value.startswith('/')
            and all(part and part not in ('.', '..') and not part.endswith(('.', ' '))
                    and re.match(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)', part, re.I) is None
                    for part in value.split('/')))


def no_link_ancestors(path: Path) -> None:
    absolute = path.absolute()
    if any(part in ('.', '..') for part in path.parts):
        raise ValueError('unsafe program path')
    if any(item.is_symlink() for item in (absolute, *absolute.parents)):
        raise ValueError('program path link forbidden')


def regular_bytes(path: Path) -> bytes:
    no_link_ancestors(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 <= before.st_size <= MAX_FILE:
            raise ValueError('unsafe or oversized program input')
        with os.fdopen(descriptor, 'rb', closefd=False) as stream:
            data = stream.read(MAX_FILE + 1)
        after, current = os.fstat(descriptor), path.lstat()
        identity = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_nlink,
                                 item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current) or len(data) != before.st_size:
            raise ValueError('program input changed')
        return data
    finally:
        os.close(descriptor)


def replace_once(data: bytes, marker: bytes, value: str) -> bytes:
    if data.count(marker) != 1:
        raise ValueError('invalid launcher trust marker')
    return data.replace(marker, value.encode('ascii'))


def original_files() -> dict[str, bytes]:
    raw = regular_bytes(ORIGINAL_ARCHIVE)
    if sha(raw) != ORIGINAL_SHA256:
        raise ValueError('original helper archive pin mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names) or len({name.casefold() for name in names}) != len(names):
            raise ValueError('original helper inventory mismatch')
        manifest_raw = archive.read('MANIFEST.json')
        if sha(manifest_raw) != ORIGINAL_MANIFEST_SHA256:
            raise ValueError('original helper manifest pin mismatch')
        manifest = json.loads(manifest_raw)
        if manifest.get('format') != 'marichevy-offline-queue-bundle-v1':
            raise ValueError('original helper format mismatch')
        expected = {item['path']: item for item in manifest['files']}
        selected = {}
        for name in ORIGINAL_FILES:
            item, data = expected[name], archive.read(name)
            if (len(data), sha(data)) != (item['bytes'], item['sha256']):
                raise ValueError('original helper file mismatch')
            selected[name] = data
        if len(selected['runtime/node.exe']) != NODE_BYTES or sha(selected['runtime/node.exe']) != NODE_SHA256:
            raise ValueError('original runtime pin mismatch')
        return selected


def build(*, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new ZIP')
    no_link_ancestors(output)
    files = original_files()
    for name in APP:
        if not safe_name(name):
            raise ValueError('invalid source allowlist')
        data = regular_bytes(SOURCE.joinpath(*name.split('/')))
        if name in ASSET_PINS and (sha(data), len(data)) != ASSET_PINS[name]:
            raise ValueError('pinned restore asset mismatch')
        files['app/' + name] = data
    files['README_WINDOWS_RU.txt'] = regular_bytes(SOURCE / 'README_WINDOWS_RU.txt')
    bootstrap, launcher, preflight = (regular_bytes(SOURCE / name) for name in (BOOTSTRAP, LAUNCHER, PREFLIGHT))
    if NODE_SHA256.encode() not in bootstrap or NODE_SHA256.encode() not in preflight:
        raise ValueError('runtime trust pin missing')
    files['BUILD.json'] = encoded({
        'format': 'marichevy-private-verification-windows-build-v1',
        'target': 'win32-x64-self-contained', 'contains_private_data': False,
        'original_helper_archive_sha256': ORIGINAL_SHA256,
        'original_helper_manifest_sha256': ORIGINAL_MANIFEST_SHA256,
        'runtime': {'version': 'v22.23.4', 'sha256': NODE_SHA256, 'bytes': NODE_BYTES},
        'native_windows_acceptance': 'pending-owner-device-check',
        'restore_scope': 'offline-four-app-tables-auth-id-stubs',
        'restore_engine': 'pglite-0.3.14-postgresql-17.5-wasm-in-memory',
        'supabase_auth_or_platform_restored': False,
        'server_concurrency_tested_by_this_bundle': False,
        'sources': {name: sha(data) for name, data in sorted(files.items())},
        'bootstrap_template_sha256': sha(bootstrap), 'launcher_template_sha256': sha(launcher),
        'preflight_template_sha256': sha(preflight),
    })
    manifest = encoded({'format': 'marichevy-private-verification-windows-bundle-v1',
        'files': [{'path': name, 'bytes': len(data), 'sha256': sha(data)} for name, data in sorted(files.items())]})
    manifest_hash = sha(manifest)
    generated_bootstrap = replace_once(bootstrap, b'__WINDOWS_MANIFEST_SHA256__', manifest_hash)
    generated_preflight = replace_once(preflight, b'__WINDOWS_BOOTSTRAP_SHA256__', sha(generated_bootstrap))
    generated_preflight = replace_once(generated_preflight, b'__WINDOWS_MANIFEST_SHA256__', manifest_hash)
    loader = replace_once(PREFLIGHT_LOADER.encode('utf8'), b'__WINDOWS_PREFLIGHT_SHA256__', sha(generated_preflight))
    command = base64.b64encode(loader.decode('utf8').encode('utf-16le')).decode('ascii')
    generated_launcher = replace_once(launcher, b'__WINDOWS_ENCODED_PREFLIGHT__', command)
    if max(map(len, generated_launcher.splitlines())) > 7000:
        raise ValueError('Windows command length exceeded')
    # Trust roots are allowed explicitly by bootstrap, like bootstrap itself.
    # CMD pins PS, PS pins Node/bootstrap/manifest, bootstrap pins the payload.
    files.update({'MANIFEST.json': manifest, 'app/' + BOOTSTRAP: generated_bootstrap,
        LAUNCHER: generated_launcher.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'),
        PREFLIGHT: generated_preflight})
    if (any(not safe_name(name) for name in files)
            or len({name.casefold() for name in files}) != len(files)
            or any(name.startswith('PRIVATE') for name in files)):
        raise ValueError('unsafe archive inventory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        try:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name, data in sorted(files.items()):
                    item = zipfile.ZipInfo(name, (2026, 10, 29, 0, 0, 0))
                    item.create_system = 3
                    item.external_attr = 0o100644 << 16
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
    return {'format': 'marichevy-private-verification-windows-report-v1',
        'outcome': 'built-code-only', 'contains_private_data': False,
        'bytes': output.stat().st_size, 'sha256': sha(output.read_bytes()),
        'file_count': len(files), 'manifest_sha256': manifest_hash,
        'bootstrap_sha256': sha(generated_bootstrap), 'preflight_sha256': sha(generated_preflight),
        'runtime_sha256': NODE_SHA256, 'original_helper_archive_sha256': ORIGINAL_SHA256,
        'native_owner_windows_acceptance': 'pending', 'native_owner_windows_passed': False,
        'production_changed': False, 'release_authorized': False,
        'restore_scope': 'offline-four-app-tables-auth-id-stubs',
        'supabase_auth_or_platform_restored': False, 'server_concurrency_tested_by_this_bundle': False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    print(json.dumps(build(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == '__main__':
    main()
