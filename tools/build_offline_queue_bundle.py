#!/usr/bin/env python3
"""Build a code-only portable Windows helper from explicitly supplied inputs.

No downloads, npm install scripts, browser profiles or private backups are read.
Dependencies must match the checked-in byte inventory and npm lockfile.
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
APP = ('bootstrap.cjs','main.cjs','selftest.cjs','capture.cjs','integrity.cjs','windows.cjs','package.json','package-lock.json')
ROOT_FILES = ('README_RU.txt','Start backup.cmd')
PACKAGES = ('@koromix/koffi-win32-x64','abstract-level','base64-js','buffer','classic-level','ieee754','is-buffer','koffi','level-supports','level-transcoder','maybe-combine-errors','module-error','napi-macros','node-gyp-build','snappyjs')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and '\\' not in name and ':' not in name and all(part not in ('','.','..') for part in name.split('/'))


def dependency_files(deps_root: Path) -> dict[str, bytes]:
    """Only the enumerated packages. Never enumerate sibling owner directories."""
    files = {}
    lock = json.loads((SOURCE/'package-lock.json').read_text())['packages']
    for name in PACKAGES:
        package = deps_root.joinpath(*name.split('/'))
        if package.is_symlink() or not package.is_dir():
            raise ValueError('missing or unsafe dependency')
        package_json = json.loads((package/'package.json').read_text())
        if package_json['name'] != name or package_json['version'] != lock['node_modules/'+name]['version']:
            raise ValueError('dependency version mismatch')
        for file in sorted(package.rglob('*')):
            if file.is_symlink():
                raise ValueError('dependency link forbidden')
            if file.is_dir():
                continue
            local = file.relative_to(package).as_posix()
            if name == 'classic-level' and local.startswith('prebuilds/') and not local.startswith('prebuilds/win32-x64/'):
                continue
            relative = name+'/'+local
            if not file.is_file() or not safe_name(relative):
                raise ValueError('unsafe dependency file')
            files[relative] = file.read_bytes()
    return files


def pe_x64(data: bytes) -> bool:
    if len(data)<128 or data[:2] != b'MZ':
        return False
    offset = struct.unpack_from('<I',data,60)[0]
    return offset+6 <= len(data) and data[offset:offset+4] == b'PE\0\0' and struct.unpack_from('<H',data,offset+4)[0] == 0x8664


def build(*, deps_root: Path, node_exe: Path, node_license: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('output must be a new ZIP')
    dependencies = dependency_files(deps_root)
    inventory = json.loads((SOURCE/'dependencies.inventory.json').read_text())
    actual = {name:{'bytes':len(data),'sha256':sha(data)} for name,data in dependencies.items()}
    if inventory['format'] != 'marichevy-windows-dependencies-v1' or actual != inventory['files']:
        raise ValueError('dependency bytes differ from reviewed inventory')
    pin=json.loads((SOURCE/'runtime-pin.json').read_text())
    runtime=node_exe.read_bytes()
    if pin['version']!='v22.23.4' or len(runtime)!=pin['node_exe_bytes'] or sha(runtime)!=pin['node_exe_sha256'] or not pe_x64(runtime):
        raise ValueError('official runtime mismatch')
    license_bytes=node_license.read_bytes()
    if b'Node.js' not in license_bytes[:500] or len(license_bytes)<10000 or sha(license_bytes)!=pin.get('node_license_sha256'):
        raise ValueError('runtime license missing')
    files={}
    for name in APP:
        source=SOURCE/name
        if source.is_symlink() or not source.is_file():
            raise ValueError('helper source missing')
        files['app/'+name]=source.read_bytes()
    for name in ROOT_FILES:
        data=(SOURCE/name).read_bytes()
        if name.endswith('.cmd'):
            data=data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
        files[name]=data
    files.update({'app/node_modules/'+name:data for name,data in dependencies.items()})
    files['runtime/node.exe']=runtime
    files['runtime/NODE-LICENSE.txt']=license_bytes
    for binary in ('app/node_modules/classic-level/prebuilds/win32-x64/classic-level.node','app/node_modules/@koromix/koffi-win32-x64/win32_x64/koffi.node'):
        if binary not in files or not pe_x64(files[binary]):
            raise ValueError('Windows x64 prebuild missing')
    build_info={
        'format':'marichevy-offline-queue-build-v1','target':'win32-x64',
        'runtime':pin,'dependency_inventory_sha256':sha((SOURCE/'dependencies.inventory.json').read_bytes()),
        'helper_sources':{name:sha(files['app/'+name]) for name in APP},
        'contains_private_data':False,'native_windows_acceptance':'required-on-owner-device-before-profile-read',
        'cloud_validation':'synthetic-fixtures-only; Windows API contract mocks are not native acceptance',
    }
    files['BUILD.json']=(json.dumps(build_info,ensure_ascii=False,indent=2)+'\n').encode()
    manifest={'format':'marichevy-offline-queue-bundle-v1','files':[{'path':name,'bytes':len(data),'sha256':sha(data)} for name,data in sorted(files.items())]}
    files['MANIFEST.json']=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive destination: failure must never overwrite or remove an old ZIP.
    with output.open('xb') as stream:
        try:
            with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
                for name,data in sorted(files.items()):
                    item=zipfile.ZipInfo(name,(2026,10,26,0,0,0));item.compress_type=zipfile.ZIP_DEFLATED
                    item.external_attr=0o100644 << 16
                    archive.writestr(item,data,compress_type=zipfile.ZIP_DEFLATED,compresslevel=9)
        except BaseException:
            stream.close();output.unlink(missing_ok=True)
            raise
    # Read the final archive back, including every CRC and exact manifest hash.
    with zipfile.ZipFile(output) as archive:
        if sorted(archive.namelist()) != sorted(files) or archive.testzip() is not None:
            raise ValueError('archive verification failed')
        for name,data in files.items():
            if archive.read(name) != data:
                raise ValueError('archive content mismatch')
    return {'outcome':'built-code-only','path':str(output),'bytes':output.stat().st_size,'sha256':sha(output.read_bytes()),'file_count':len(files)}


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--deps-root',required=True,type=Path)
    parser.add_argument('--node-exe',required=True,type=Path)
    parser.add_argument('--node-license',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    print(json.dumps(build(**vars(args)),ensure_ascii=False))


if __name__=='__main__':
    main()
