#!/usr/bin/env python3
"""Package the existing family site and reviewed SQL, without deploying anything."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path('/workspace/private-family-release-candidate')
STATIC_FILES = (
    'index.html', 'favicon.svg', 'favicon.ico', 'favicon-32.png',
    'apple-touch-icon.png', 'CNAME',
)
OPERATOR_FILES = (
    'server/001_family_state_cas.sql',
    'server/002_restrict_table_capabilities.sql',
    'server/003_bound_membership_lookup.sql',
    'server/activate_household.sql',
    'server/rollback_household.sql',
    'docs/RELEASE_RUNBOOK.md',
    'docs/PRIVATE_RESTORE_ACCEPTANCE.md',
    'docs/DEVICE_QUEUE_CAPTURE_MAC_RU.md',
    'docs/LOCAL_QUEUE_BACKUP_RU.md',
    'docs/SYNC_SERVER.md',
    'docs/PRODUCTION_SCHEMA_FINDINGS.md',
    'docs/FAMILY_RELEASE_ARTIFACTS_RU.md',
)
SOURCE_FILES = STATIC_FILES + OPERATOR_FILES
OUTPUT_FILES = frozenset({
    'family-static.zip', 'family-static.MANIFEST.json',
    'family-operator.zip', 'family-operator.MANIFEST.json',
})
ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)
MAX_SOURCE_BYTES = 32 * 1024 * 1024
FORMAT = 'marichevy-family-release-manifest-v1'


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def absolute_path(path: Path) -> Path:
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Parent path components are not accepted')
    return path


def open_directory(path: Path) -> int:
    """Walk every component through directory FDs; never follow a symlink."""
    path = absolute_path(path)
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except (OSError, ValueError):
        os.close(descriptor)
        raise ValueError('A directory is unavailable or contains a symbolic link') from None


def open_source(root_fd: int, name: str) -> int:
    if name not in SOURCE_FILES:
        raise ValueError('Source is outside the explicit family allowlist')
    relative = PurePosixPath(name)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Source must be an explicit relative path')
    directory_fd = os.dup(root_fd)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child
        descriptor = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory_fd)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise ValueError('Family sources must be regular files')
        return descriptor
    except OSError:
        raise ValueError('A family source is unavailable or contains a symbolic link') from None
    finally:
        os.close(directory_fd)


def file_identity(info: os.stat_result) -> tuple:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_source_once(root_fd: int, name: str) -> tuple[bytes, tuple]:
    descriptor = open_source(root_fd, name)
    with os.fdopen(descriptor, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > MAX_SOURCE_BYTES:
            raise ValueError('A family source exceeds the size limit')
        payload = stream.read(MAX_SOURCE_BYTES + 1)
        after = os.fstat(stream.fileno())
        if (len(payload) > MAX_SOURCE_BYTES or len(payload) != before.st_size
                or file_identity(before) != file_identity(after)):
            raise ValueError('A source changed while it was read')
        return payload, file_identity(after)


def repository_snapshot(root: Path) -> dict:
    def git(*arguments: str) -> bytes:
        # Do not inherit credential/helper/proxy variables or user-wide Git config.
        environment = {'PATH': os.defpath, 'LC_ALL': 'C', 'GIT_CONFIG_NOSYSTEM': '1',
                       'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_NO_LAZY_FETCH': '1',
                       'GIT_NO_REPLACE_OBJECTS': '1'}
        result = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                                 '-c', 'core.untrackedCache=false', '-c', 'core.hooksPath=/dev/null',
                                 '-c', 'core.excludesFile=/dev/null', '-C', str(root), *arguments],
                                check=False, capture_output=True, env=environment, timeout=20)
        if result.returncode:
            raise ValueError('A readable Git checkout is required')
        return result.stdout
    if Path(os.fsdecode(git('rev-parse', '--show-toplevel').strip())).absolute() != root:
        raise ValueError('Source root must be the Git checkout root')
    head = git('rev-parse', '--verify', 'HEAD').strip().decode('ascii')
    if len(head) not in (40, 64) or any(c not in '0123456789abcdef' for c in head):
        raise ValueError('A committed Git HEAD is required')
    # Never use status/diff-files: they can hash excluded files and execute clean
    # filters. Cached diff and ls-files read Git metadata, not working-file bytes.
    staged = git('diff-index', '--cached', '--name-only', '-z', '--no-renames',
                 '--no-ext-diff', '--no-textconv', '--ignore-submodules=all', 'HEAD', '--')
    untracked = git('ls-files', '--others', '--exclude-standard', '--directory', '-z')
    index = git('ls-files', '--stage', '--debug', '-z')
    pattern = re.compile(
        rb'([0-7]{6}) ([0-9a-f]{40}|[0-9a-f]{64}) ([0-3])\t([^\x00]*)\x00'
        rb'  ctime: (\d+):(\d+)\n  mtime: (\d+):(\d+)\n'
        rb'  dev: (\d+)\tino: (\d+)\n  uid: (\d+)\tgid: (\d+)\n'
        rb'  size: (\d+)\tflags: ([0-9a-fA-F]+)\n')
    entries, metadata, cursor = {}, [], 0
    metadata_dirty = False
    for match in pattern.finditer(index):
        if match.start() != cursor:
            raise ValueError('Unsupported Git index metadata')
        cursor = match.end()
        mode, object_id, stage, raw_name, cs, cn, ms, mn, dev, ino, uid, gid, size, flags = match.groups()
        name = os.fsdecode(raw_name)
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe Git index path')
        entries[name] = (mode.decode('ascii'), object_id.decode('ascii'), int(stage))
        # Stat only. Even a changed excluded .env/backup is never opened or hashed.
        try:
            info = (root / name).lstat()
            actual = (info.st_ctime_ns, info.st_mtime_ns, info.st_dev & 0xffffffff,
                      info.st_ino & 0xffffffff, info.st_uid, info.st_gid,
                      info.st_size & 0xffffffff, stat.S_IFMT(info.st_mode), bool(info.st_mode & 0o111))
        except OSError:
            actual = None
        expected_kind = stat.S_IFLNK if mode == b'120000' else stat.S_IFREG
        expected = (int(cs) * 1000000000 + int(cn), int(ms) * 1000000000 + int(mn),
                    int(dev), int(ino), int(uid), int(gid), int(size), expected_kind, mode == b'100755')
        if actual != expected or int(stage) != 0 or int(flags, 16) != 0:
            metadata_dirty = True
        metadata.append((name, actual))
    if cursor != len(index):
        raise ValueError('Unsupported Git index metadata')
    return {'git_head': head, 'git_dirty': bool(staged or untracked or metadata_dirty),
            '_index': entries, '_identity': hashlib.sha256(index + staged + untracked
                + canonical_json(metadata)).hexdigest()}


def zip_bytes(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in sorted(files.items()):
            member = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            member.create_system = 3
            member.compress_type = zipfile.ZIP_DEFLATED
            member.external_attr = (stat.S_IFREG | 0o600) << 16
            archive.writestr(member, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return output.getvalue()


def open_output(output: Path, root: Path) -> int:
    if output == root or root in output.parents:
        raise ValueError('Family artifacts must be outside the checkout')
    parent_fd = open_directory(output.parent)
    try:
        try:
            os.mkdir(output.name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass
        try:
            descriptor = os.open(output.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                 dir_fd=parent_fd)
        except OSError:
            raise ValueError('Output must be a private directory without symbolic links') from None
    finally:
        os.close(parent_fd)
    info = os.fstat(descriptor)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(descriptor)
        raise ValueError('Output directory must be owned by this user with mode 0700')
    return descriptor


def validate_existing_output(directory_fd: int, expected: dict[str, bytes]) -> bool:
    existing = set(os.listdir(directory_fd))
    if not existing:
        return False
    if existing != OUTPUT_FILES:
        raise ValueError('Output has unexpected or incomplete files; use a fresh private directory')
    for name in sorted(existing):
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                 dir_fd=directory_fd)
        except OSError:
            raise ValueError('Existing output must not contain symbolic links') from None
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
                raise ValueError('Existing artifacts must be owned regular files with mode 0600')
            if info.st_size != len(expected[name]) or stream.read(len(expected[name]) + 1) != expected[name]:
                raise ValueError('Output contains a different build; use a fresh private directory')
    return True


def write_output(directory_fd: int, files: dict[str, bytes]) -> None:
    created = []
    try:
        for name, payload in sorted(files.items()):
            descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory_fd)
            created.append(name)
            with os.fdopen(descriptor, 'wb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        os.fsync(directory_fd)
    except Exception:
        for name in created:
            os.unlink(name, dir_fd=directory_fd)
        raise


def build(output: Path = DEFAULT_OUTPUT, *, root: Path = ROOT) -> dict:
    root, output = absolute_path(root), absolute_path(output)
    root_fd = open_directory(root)
    try:
        before = repository_snapshot(root)
        sources, identities = {}, {}
        for name in SOURCE_FILES:
            sources[name], identities[name] = read_source_once(root_fd, name)
        after = repository_snapshot(root)
        if before != after:
            raise ValueError('Git changed during the build; use a stable checkout')
        # Check identity/size/clocks without reading any source for a second time.
        for name, identity in identities.items():
            descriptor = open_source(root_fd, name)
            try:
                if file_identity(os.fstat(descriptor)) != identity:
                    raise ValueError('A source changed during the build')
            finally:
                os.close(descriptor)
    finally:
        os.close(root_fd)

    all_hashes = {name: hashlib.sha256(payload).hexdigest() for name, payload in sorted(sources.items())}
    snapshot_sha = hashlib.sha256(canonical_json(all_hashes)).hexdigest()
    provenance = {key: before[key] for key in ('git_head', 'git_dirty')}
    # Compare our already-read bytes with index blob IDs, without running Git
    # filters or opening the sources again. Metadata uncertainty stays dirty.
    for name, payload in sources.items():
        record = before['_index'].get(name)
        digest = hashlib.sha256 if record and len(record[1]) == 64 else hashlib.sha1
        blob = digest(b'blob ' + str(len(payload)).encode('ascii') + b'\0' + payload).hexdigest()
        if not record or record[2] != 0 or blob != record[1]:
            provenance['git_dirty'] = True
    files, manifests = {}, {}
    for kind, names in (('static', STATIC_FILES), ('operator', OPERATOR_FILES)):
        archive_name = 'family-' + kind + '.zip'
        archive = zip_bytes({name: sources[name] for name in names})
        manifest = {
            'format': FORMAT,
            'status': 'candidate-not-published',
            'kind': kind,
            **provenance,
            'git_dirty_basis': 'conservative-index-metadata-and-selected-source-bytes',
            'source_snapshot_sha256': snapshot_sha,
            'index_sha256': all_hashes['index.html'],
            'archive': {'name': archive_name, 'bytes': len(archive),
                        'sha256': hashlib.sha256(archive).hexdigest()},
            'files': {name: all_hashes[name] for name in sorted(names)},
        }
        files[archive_name] = archive
        files['family-' + kind + '.MANIFEST.json'] = canonical_json(manifest)
        manifests[kind] = manifest
    directory_fd = open_output(output, root)
    try:
        if not validate_existing_output(directory_fd, files):
            write_output(directory_fd, files)
    finally:
        os.close(directory_fd)
    return manifests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        manifests = build(args.output_dir)
    except (ValueError, OSError, subprocess.TimeoutExpired) as error:
        parser.exit(1, 'Family release build refused: ' + str(error) + '\n')
    print('Family candidate built; NOT PUBLISHED. Git dirty: '
          + str(manifests['static']['git_dirty']).lower() + '.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
