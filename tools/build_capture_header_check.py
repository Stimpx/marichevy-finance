#!/usr/bin/env python3
"""Build a one-file, offline header classifier; never read owner backup inputs."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/private_verify/capture-header-check.html'
HTML_NAME = 'Check capture headers.html'
MAX_SOURCE = 16 * 1024


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def no_links(path: Path) -> None:
    if any(part in ('.', '..') for part in path.parts):
        raise ValueError('unsafe code path')
    if any(part.is_symlink() for part in (path.absolute(), *path.absolute().parents)):
        raise ValueError('linked code path forbidden')


def rendered() -> bytes:
    no_links(SOURCE)
    descriptor = os.open(SOURCE, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= MAX_SOURCE:
            raise ValueError('invalid code source')
        raw = os.read(descriptor, MAX_SOURCE + 1)
        after, current = os.fstat(descriptor), SOURCE.lstat()
        identity = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
                                  value.st_size, value.st_mtime_ns, value.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current) or len(raw) != before.st_size:
            raise ValueError('code source changed')
    finally:
        os.close(descriptor)
    text = raw.decode('utf8', errors='strict')
    for tag, marker in (('script', '__SCRIPT_SHA256__'), ('style', '__STYLE_SHA256__')):
        blocks = re.findall(r'<' + tag + r'>(.*?)</' + tag + r'>', text, flags=re.S)
        if len(blocks) != 1 or text.count(marker) != 1:
            raise ValueError('invalid inline code inventory')
        digest = base64.b64encode(hashlib.sha256(blocks[0].encode('utf8')).digest()).decode('ascii')
        text = text.replace(marker, digest)
    if '__SCRIPT_' in text or '__STYLE_' in text:
        raise ValueError('unresolved content security policy')
    return text.encode('utf8')


def build(*, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new ZIP')
    no_links(output)
    html = rendered()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        try:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                item = zipfile.ZipInfo(HTML_NAME, (2026, 10, 29, 0, 0, 0))
                item.create_system = 3
                item.external_attr = 0o100644 << 16
                archive.writestr(item, html, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        except BaseException:
            stream.close()
            output.unlink(missing_ok=True)
            raise
    with zipfile.ZipFile(output) as archive:
        if archive.namelist() != [HTML_NAME] or archive.testzip() is not None or archive.read(HTML_NAME) != html:
            raise ValueError('archive verification failed')
    return {
        'format': 'marichevy-capture-header-check-build-v1',
        'outcome': 'built-code-only-header-diagnostic',
        'contains_private_data': False, 'file_count': 1,
        'bytes': output.stat().st_size, 'sha256': sha(output.read_bytes()),
        'html_bytes': len(html), 'html_sha256': sha(html),
        'network_access_allowed_by_csp': False, 'original_inputs_modified': False,
        'compares_financial_records': False, 'restore_execution_verified': False,
        'production_changed': False, 'release_authorized': False,
        'native_owner_windows_acceptance': 'pending',
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(**vars(parser.parse_args())), sort_keys=True))


if __name__ == '__main__':
    main()
