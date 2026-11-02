#!/usr/bin/env python3
"""Build a code-only universal Mac backup helper from verified explicit inputs.

This builder does not download, install, execute native binaries, inspect browser
profiles or read private backups. Dependency and runtime bytes must match pins.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tools/offline_queue'
APP = ('mac-bootstrap.cjs', 'mac-main.cjs', 'macos.cjs', 'capture.cjs',
       'integrity.cjs', 'package.json', 'package-lock.json')
ROOT_FILES = ('README_MAC_RU.txt', 'Start Mac backup.command')
PACKAGES = ('@koromix/koffi-darwin-arm64', '@koromix/koffi-darwin-x64',
            'abstract-level', 'base64-js', 'buffer', 'classic-level', 'ieee754',
            'is-buffer', 'koffi', 'level-supports', 'level-transcoder',
            'maybe-combine-errors', 'module-error', 'napi-macros',
            'node-gyp-build', 'snappyjs')
CPUS = {'arm64': 0x0100000C, 'x64': 0x01000007}
MAX_FILE = 160 * 1024 * 1024


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def regular_bytes(file: Path, *, maximum: int = MAX_FILE) -> bytes:
    if file.is_symlink() or not file.is_file() or file.stat().st_size > maximum:
        raise ValueError('unsafe or oversized input file')
    return file.read_bytes()


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return (bool(name) and len(name) <= 500 and not path.is_absolute()
            and not any(ord(c) < 32 or c in '\\:<>"|?*' for c in name)
            and all(part not in ('', '.', '..') for part in name.split('/')))


def macho_cpus(data: bytes) -> set[int]:
    """Parse bounded Mach-O headers, including the universal dependency binary.

    This establishes binary format/CPU only. It does not establish loadability
    or native macOS acceptance, which must pass on the owner's actual device.
    """
    if len(data) < 32:
        return set()
    if data[:4] == b'\xcf\xfa\xed\xfe':
        return {struct.unpack_from('<I', data, 4)[0]}
    if data[:4] == b'\xfe\xed\xfa\xcf':
        return {struct.unpack_from('>I', data, 4)[0]}
    if data[:4] not in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
        return set()
    wide = data[:4] == b'\xca\xfe\xba\xbf'
    count = struct.unpack_from('>I', data, 4)[0]
    size = 32 if wide else 20
    if not 1 <= count <= 8 or 8 + count * size > len(data):
        return set()
    found = set()
    for index in range(count):
        base = 8 + index * size
        cpu = struct.unpack_from('>I', data, base)[0]
        offset, length = struct.unpack_from('>QQ' if wide else '>II', data, base + 8)
        if offset < 8 + count * size or length < 32 or offset + length > len(data):
            return set()
        nested = macho_cpus(data[offset:offset + length])
        if nested != {cpu} or cpu in found:
            return set()
        found.add(cpu)
    return found


def dependency_files(deps_root: Path) -> dict[str, bytes]:
    files = {}
    lock = json.loads(regular_bytes(SOURCE / 'package-lock.json', maximum=2 * 1024 * 1024))['packages']
    for name in PACKAGES:
        package = deps_root.joinpath(*name.split('/'))
        if package.is_symlink() or not package.is_dir():
            raise ValueError('missing or unsafe dependency')
        package_json = json.loads(regular_bytes(package / 'package.json', maximum=2 * 1024 * 1024))
        if (package_json['name'] != name or
                package_json['version'] != lock['node_modules/' + name]['version']):
            raise ValueError('dependency version mismatch')
        for file in sorted(package.rglob('*')):
            if file.is_symlink():
                raise ValueError('dependency link forbidden')
            if file.is_dir():
                continue
            local = file.relative_to(package).as_posix()
            if (name == 'classic-level' and local.startswith('prebuilds/')
                    and not local.startswith('prebuilds/darwin-x64+arm64/')):
                continue
            relative = name + '/' + local
            if not file.is_file() or not safe_name(relative) or file.stat().st_size > MAX_FILE:
                raise ValueError('unsafe dependency file')
            files[relative] = regular_bytes(file)
    return files


def build(*, deps_root: Path, runtimes_root: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new ZIP')
    dependencies = dependency_files(deps_root)
    inventory_data = regular_bytes(SOURCE / 'dependencies-macos.inventory.json', maximum=2 * 1024 * 1024)
    inventory = json.loads(inventory_data)
    actual = {name: {'bytes': len(data), 'sha256': sha(data)}
              for name, data in dependencies.items()}
    if (inventory['format'] != 'marichevy-macos-dependencies-v1' or
            inventory['lockfile_sha256'] != sha(regular_bytes(SOURCE / 'package-lock.json', maximum=2 * 1024 * 1024))
            or actual != inventory['files']):
        raise ValueError('dependency bytes differ from reviewed inventory')
    pin = json.loads(regular_bytes(SOURCE / 'runtime-pin-macos.json', maximum=2 * 1024 * 1024))
    if (pin.get('format') != 'marichevy-macos-runtime-pin-v1'
            or pin['version'] != 'v22.23.4' or set(pin['architectures']) != set(CPUS)):
        raise ValueError('runtime pin mismatch')
    files = {}
    for name in APP:
        file = SOURCE / name
        if file.is_symlink() or not file.is_file():
            raise ValueError('helper source missing')
        files['app/' + name] = regular_bytes(file)
    for name in ROOT_FILES:
        files[name] = regular_bytes(SOURCE / name)
    for arch, cpu in CPUS.items():
        binary = runtimes_root / arch / 'node'
        license_file = runtimes_root / arch / 'LICENSE'
        if binary.is_symlink() or license_file.is_symlink():
            raise ValueError('runtime link forbidden')
        data, license_data = regular_bytes(binary), regular_bytes(license_file, maximum=2 * 1024 * 1024)
        expected = pin['architectures'][arch]
        if (len(data) > MAX_FILE or len(data) != expected['node_bytes']
                or sha(data) != expected['node_sha256'] or macho_cpus(data) != {cpu}):
            raise ValueError('official runtime mismatch')
        if (len(license_data) < 10000 or b'Node.js' not in license_data[:500]
                or sha(license_data) != expected['node_license_sha256']):
            raise ValueError('runtime license mismatch')
        files['runtime/' + arch + '/node'] = data
        files['runtime/' + arch + '/NODE-LICENSE.txt'] = license_data
    files.update({'app/node_modules/' + name: data for name, data in dependencies.items()})
    required_native = {
        'classic-level/prebuilds/darwin-x64+arm64/classic-level.node': set(CPUS.values()),
        '@koromix/koffi-darwin-arm64/darwin_arm64/koffi.node': {CPUS['arm64']},
        '@koromix/koffi-darwin-x64/darwin_x64/koffi.node': {CPUS['x64']},
    }
    for name, cpus in required_native.items():
        if name not in dependencies or macho_cpus(dependencies[name]) != cpus:
            raise ValueError('Mac prebuild CPU mismatch')
    build_info = {
        'format': 'marichevy-offline-queue-macos-build-v1', 'target': 'darwin-universal',
        'runtime': pin, 'dependency_inventory_sha256': sha(inventory_data),
        'helper_sources': {name: sha(files['app/' + name]) for name in APP},
        'contains_private_data': False,
        'native_macos_acceptance': 'mandatory-fictional-selftest-on-owner-device-before-profile-read',
        'cloud_validation': 'synthetic-only; Mach-O parsing and API mocks are not native acceptance',
    }
    files['BUILD.json'] = (json.dumps(build_info, ensure_ascii=False, indent=2) + '\n').encode()
    manifest = {'format': 'marichevy-offline-queue-macos-bundle-v1',
                'files': [{'path': name, 'bytes': len(data), 'sha256': sha(data)}
                          for name, data in sorted(files.items())]}
    files['MANIFEST.json'] = (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode()
    if len({name.casefold() for name in files}) != len(files):
        raise ValueError('case-insensitive archive path collision')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        try:
            with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                for name, data in sorted(files.items()):
                    item = zipfile.ZipInfo(name, (2026, 10, 27, 0, 0, 0))
                    item.create_system = 3
                    executable = name == 'Start Mac backup.command' or name in ('runtime/arm64/node', 'runtime/x64/node')
                    item.external_attr = (0o100755 if executable else 0o100644) << 16
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
    return {'outcome': 'built-code-only', 'path': str(output), 'bytes': output.stat().st_size,
            'sha256': sha(output.read_bytes()), 'file_count': len(files)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deps-root', required=True, type=Path)
    parser.add_argument('--runtimes-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    print(json.dumps(build(**vars(parser.parse_args())), ensure_ascii=False))


if __name__ == '__main__':
    main()
