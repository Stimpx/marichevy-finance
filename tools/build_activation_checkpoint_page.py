#!/usr/bin/env python3
"""Build an offline code-only page; no owner file, network or SQL execution."""
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
SOURCE = ROOT / 'tools/private_verify/activation-checkpoint.html'
SQL_SOURCE = ROOT / 'server/activate_household_api.sql'
SQL_SHA256 = '7fc72248cd65e790dfec12abc4da1811ae2146f414b8be46cd5cd7ae5244e248'
HTML_NAME = 'Prepare activation checkpoint.html'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def no_links(path):
    if any(part in ('.', '..') for part in path.parts):
        raise ValueError('unsafe code path')
    if any(part.is_symlink() for part in (path.absolute(), *path.absolute().parents)):
        raise ValueError('linked code path forbidden')


def read_code(path, maximum):
    no_links(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= maximum:
            raise ValueError('invalid code source')
        raw = os.read(descriptor, maximum + 1)
        after, current = os.fstat(descriptor), path.lstat()
        identity = lambda x: (x.st_dev, x.st_ino, x.st_mode, x.st_nlink, x.st_size, x.st_mtime_ns, x.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current) or len(raw) != before.st_size:
            raise ValueError('code source changed')
        return raw
    finally:
        os.close(descriptor)


def rendered():
    text = read_code(SOURCE, 128 * 1024).decode('utf8', errors='strict')
    sql = read_code(SQL_SOURCE, 32 * 1024)
    if sha(sql) != SQL_SHA256 or text.count('__ACTIVATION_SQL_JSON__') != 1:
        raise ValueError('reviewed SQL pin mismatch')
    text = text.replace('__ACTIVATION_SQL_JSON__', json.dumps(sql.decode('utf8'), ensure_ascii=True).replace('</', r'<\/'))
    for tag, marker in (('script', '__SCRIPT_SHA256__'), ('style', '__STYLE_SHA256__')):
        blocks = re.findall(r'<' + tag + r'>(.*?)</' + tag + r'>', text, flags=re.S)
        if len(blocks) != 1 or text.count(marker) != 1:
            raise ValueError('invalid inline inventory')
        text = text.replace(marker, base64.b64encode(hashlib.sha256(blocks[0].encode()).digest()).decode())
    if re.search(r'__(?:SCRIPT|STYLE|ACTIVATION)_', text):
        raise ValueError('unresolved code marker')
    return text.encode('utf8')


def build(*, output):
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
    return {'format': 'marichevy-activation-checkpoint-build-v1', 'outcome': 'built-code-only-offline-preparation',
            'file_count': 1, 'bytes': output.stat().st_size, 'sha256': sha(output.read_bytes()),
            'html_bytes': len(html), 'html_sha256': sha(html), 'activation_sql_sha256': SQL_SHA256,
            'contains_private_data': False, 'network_used': False, 'production_changed': False,
            'activation_executed': False, 'activation_receipt_created': False,
            'native_owner_windows_acceptance': 'pending'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(build(**vars(parser.parse_args())), sort_keys=True))


if __name__ == '__main__':
    main()
