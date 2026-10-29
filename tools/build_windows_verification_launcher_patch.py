#!/usr/bin/env python3
"""Build a one-file diagnostic launcher patch for the published Windows ZIP.

This reuses the exact original preflight and application/runtime bytes. It does
not read owner copies or execute the launcher, and does not establish a fix.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    '_windows_verification_shared_builder',
    Path(__file__).with_name('build_private_verification_windows_bundle.py'))
SHARED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SHARED)
ORIGINAL_ARCHIVE = ROOT / 'preview/windows-private-verification-v95.zip'
ORIGINAL_SHA256 = 'd18b80b6067dc8ed6a3be9861e21efdcf5949bdf9d316132f4cc141284253401'
ORIGINAL_PREFLIGHT_SHA256 = '7e534da4bf7b799f97fb060a5b1fde8120ddfc447b823cc9a6c701f2e588e0e3'
ORIGINAL_MANIFEST_SHA256 = 'e2b1bf86f6bec5d8619b14082ba011d3158bb10cab55d179ec4d90e120607cd0'
ORIGINAL_BOOTSTRAP_SHA256 = 'ad80520b8c68afe0fe01bfc210677a9871f598c589675c8d0a15f141b3c4dde8'
LAUNCHER = 'Start Windows verification.cmd'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def original_preflight() -> bytes:
    raw = SHARED.regular_bytes(ORIGINAL_ARCHIVE)
    if sha(raw) != ORIGINAL_SHA256:
        raise ValueError('original verifier archive pin mismatch')
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = archive.namelist()
        if (len(names) != 30 or len(set(names)) != len(names)
                or len({name.casefold() for name in names}) != len(names)
                or any(not SHARED.safe_name(name) or name.startswith('PRIVATE') for name in names)):
            raise ValueError('original verifier inventory mismatch')
        preflight = archive.read(SHARED.PREFLIGHT)
        if sha(preflight) != ORIGINAL_PREFLIGHT_SHA256:
            raise ValueError('original verifier preflight pin mismatch')
        if sha(archive.read('MANIFEST.json')) != ORIGINAL_MANIFEST_SHA256:
            raise ValueError('original verifier manifest pin mismatch')
        if sha(archive.read('app/windows-bootstrap.cjs')) != ORIGINAL_BOOTSTRAP_SHA256:
            raise ValueError('original verifier bootstrap pin mismatch')
        return preflight


def build(*, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new ZIP')
    SHARED.no_link_ancestors(output)
    preflight = original_preflight()
    template = SHARED.regular_bytes(SHARED.SOURCE / LAUNCHER)
    loader = SHARED.replace_once(SHARED.PREFLIGHT_LOADER.encode('utf8'),
        b'__WINDOWS_PREFLIGHT_SHA256__', sha(preflight))
    command = base64.b64encode(loader.decode('utf8').encode('utf-16le')).decode('ascii')
    launcher = SHARED.replace_once(template, b'__WINDOWS_ENCODED_PREFLIGHT__', command)
    launcher = launcher.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    if max(map(len, launcher.splitlines())) > 7000:
        raise ValueError('Windows command length exceeded')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        try:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                item = zipfile.ZipInfo(LAUNCHER, (2026, 10, 29, 0, 0, 0))
                item.create_system = 3
                item.external_attr = 0o100644 << 16
                archive.writestr(item, launcher, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        except BaseException:
            stream.close()
            output.unlink(missing_ok=True)
            raise
    with zipfile.ZipFile(output) as archive:
        if archive.namelist() != [LAUNCHER] or archive.testzip() is not None or archive.read(LAUNCHER) != launcher:
            raise ValueError('patch archive verification failed')
    return {
        'format': 'marichevy-windows-verification-launcher-patch-report-v1',
        'outcome': 'diagnostic-launcher-only', 'contains_private_data': False,
        'bytes': output.stat().st_size, 'sha256': sha(output.read_bytes()),
        'file_count': 1, 'launcher_sha256': sha(launcher),
        'original_archive_sha256': ORIGINAL_SHA256,
        'original_preflight_sha256': ORIGINAL_PREFLIGHT_SHA256,
        'original_manifest_sha256': ORIGINAL_MANIFEST_SHA256,
        'original_bootstrap_sha256': ORIGINAL_BOOTSTRAP_SHA256,
        'original_archive_unchanged': True, 'application_payload_changed': False,
        'reads_owner_inputs': False, 'root_cause_confirmed': False, 'fix_confirmed': False,
        'native_owner_windows_acceptance': 'pending',
        'production_changed': False, 'main_changed': False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    print(json.dumps(build(**vars(parser.parse_args())), ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
