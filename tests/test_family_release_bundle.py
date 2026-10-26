"""Family-only packages from a wholly fictional checkout; no network/private input."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_family_release', ROOT / 'tools/build_family_release.py')
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)

STATIC = {'index.html', 'favicon.svg', 'favicon.ico', 'favicon-32.png', 'apple-touch-icon.png', 'CNAME'}
OPERATOR = {
    'server/001_family_state_cas.sql', 'server/002_restrict_table_capabilities.sql',
    'server/003_bound_membership_lookup.sql', 'server/activate_household.sql',
    'server/rollback_household.sql', 'docs/RELEASE_RUNBOOK.md',
    'docs/PRIVATE_RESTORE_ACCEPTANCE.md', 'docs/DEVICE_QUEUE_CAPTURE_MAC_RU.md',
    'docs/LOCAL_QUEUE_BACKUP_RU.md', 'docs/SYNC_SERVER.md',
    'docs/PRODUCTION_SCHEMA_FINDINGS.md', 'docs/FAMILY_RELEASE_ARTIFACTS_RU.md',
}
OUTPUT = {'family-static.zip', 'family-operator.zip',
          'family-static.MANIFEST.json', 'family-operator.MANIFEST.json'}


class FamilyReleaseBundle(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'fictional-checkout'
        self.root.mkdir()
        for name in sorted(STATIC | OPERATOR):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('Fictional reviewed source: ' + name + '\n').encode())
        # Deliberately present, but excluded inputs must never be read or packaged.
        for name in ('public/index.html', 'public/accounts.js', 'server/004_public_accounts.sql',
                     'server/account_gateway.py', 'preview/safe-demo.zip',
                     'backups/fictional-PRIVATE.json', '.env', 'auth-users.json'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'EXCLUDED-FICTIONAL-SENTINEL')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Fictional Builder', '-c', 'user.email=builder@example.invalid',
                 'commit', '-qm', 'Fictional family release fixture')
        self.output = self.base / 'private-output'

    def git(self, *arguments):
        return subprocess.run(['git', '-C', str(self.root), *arguments], check=True,
                              text=True, capture_output=True).stdout.strip()

    def build(self, output=None):
        return bundle.build(output or self.output, root=self.root)

    def output_bytes(self):
        return {path.name: path.read_bytes() for path in self.output.iterdir()}

    def test_exact_six_static_files_and_separate_operator_scope(self):
        manifests = self.build()
        self.assertEqual({path.name for path in self.output.iterdir()}, OUTPUT)
        self.assertFalse(manifests['static']['git_dirty'])
        for kind, expected in (('static', STATIC), ('operator', OPERATOR)):
            with self.subTest(kind=kind), zipfile.ZipFile(self.output / ('family-' + kind + '.zip')) as archive:
                self.assertEqual(set(archive.namelist()), expected)
                self.assertEqual(len(archive.namelist()), len(expected))
                self.assertIsNone(archive.testzip())
                for member in archive.infolist():
                    self.assertEqual(archive.read(member), (self.root / member.filename).read_bytes())
                    self.assertNotIn(b'EXCLUDED-FICTIONAL-SENTINEL', archive.read(member))
                    self.assertTrue(stat.S_ISREG(member.external_attr >> 16))
                    self.assertEqual(stat.S_IMODE(member.external_attr >> 16), 0o600)
                    self.assertEqual(member.date_time, bundle.ZIP_TIMESTAMP)
                self.assertFalse(any('MANIFEST' in name or name.startswith(('public/', 'preview/', 'backups/'))
                                     or '004_' in name or 'gateway' in name or name in ('.env', 'auth-users.json')
                                     for name in archive.namelist()))

    def test_external_manifests_bind_source_git_and_archive_hashes(self):
        manifests = self.build()
        all_hashes = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                      for name in sorted(STATIC | OPERATOR)}
        snapshot = (json.dumps(all_hashes, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
        for kind, expected in (('static', STATIC), ('operator', OPERATOR)):
            manifest = json.loads((self.output / ('family-' + kind + '.MANIFEST.json')).read_bytes())
            self.assertEqual(manifest, manifests[kind])
            self.assertEqual(manifest['git_head'], self.git('rev-parse', 'HEAD'))
            self.assertFalse(manifest['git_dirty'])
            self.assertEqual(manifest['status'], 'candidate-not-published')
            self.assertEqual(manifest['source_snapshot_sha256'], hashlib.sha256(snapshot).hexdigest())
            self.assertEqual(manifest['index_sha256'], all_hashes['index.html'])
            self.assertEqual(manifest['files'], {name: all_hashes[name] for name in sorted(expected)})
            archive = self.output / manifest['archive']['name']
            self.assertEqual(manifest['archive']['bytes'], archive.stat().st_size)
            self.assertEqual(manifest['archive']['sha256'], hashlib.sha256(archive.read_bytes()).hexdigest())

    def test_private_modes_determinism_and_sources_read_once(self):
        original = bundle.read_source_once
        with mock.patch.object(bundle, 'read_source_once', wraps=original) as reader:
            self.build()
        self.assertEqual([call.args[1] for call in reader.call_args_list], list(bundle.SOURCE_FILES))
        first = self.output_bytes()
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertEqual(self.output.stat().st_uid, os.geteuid())
        for path in self.output.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.build()
        self.assertEqual(self.output_bytes(), first)
        second = self.base / 'other-private-output'
        self.build(second)
        self.assertEqual({path.name: path.read_bytes() for path in second.iterdir()}, first)

    def test_changed_source_and_untracked_file_are_honestly_dirty(self):
        initial = self.build()
        (self.root / 'index.html').write_bytes(b'Fictional changed client\n')
        (self.root / 'untracked-fictional-note.txt').write_text('Fictional draft')
        changed_output = self.base / 'changed-private-output'
        changed = self.build(changed_output)
        self.assertTrue(changed['static']['git_dirty'])
        self.assertEqual(changed['static']['git_head'], initial['static']['git_head'])
        self.assertNotEqual(changed['static']['index_sha256'], initial['static']['index_sha256'])
        with zipfile.ZipFile(changed_output / 'family-static.zip') as archive:
            self.assertEqual(archive.read('index.html'), b'Fictional changed client\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Fictional Builder', '-c', 'user.email=builder@example.invalid',
                 'commit', '-qm', 'Fictional next reviewed client')
        committed = self.build(self.base / 'committed-private-output')
        self.assertFalse(committed['static']['git_dirty'])
        self.assertNotEqual(committed['static']['git_head'], initial['static']['git_head'])
        self.assertEqual(committed['static']['index_sha256'], changed['static']['index_sha256'])

    def test_mutating_an_already_dirty_source_during_build_fails_before_output(self):
        source = self.root / 'index.html'
        source.write_bytes(b'Fictional initial unsaved client\n')
        original = bundle.read_source_once
        def mutate(root_fd, name):
            result = original(root_fd, name)
            if name == 'index.html':
                source.write_bytes(b'Fictional competing changed client\n')
            return result
        with mock.patch.object(bundle, 'read_source_once', side_effect=mutate):
            with self.assertRaisesRegex(ValueError, 'changed during'):
                self.build()
        self.assertFalse(self.output.exists())

    def test_excluded_dirty_env_never_runs_git_clean_filters_or_gets_opened(self):
        marker = self.base / 'filter-executed.txt'
        helper = self.base / 'fictional-filter.py'
        helper.write_text(
            'import pathlib,sys\n'
            + 'pathlib.Path(' + repr(str(marker)) + ').write_text("FILTER-RAN")\n'
            + 'sys.stdout.buffer.write(sys.stdin.buffer.read())\n')
        (self.root / '.gitattributes').write_text('.env filter=fictional\n')
        self.git('config', 'filter.fictional.clean', 'python3 ' + str(helper))
        self.git('add', '.')
        self.git('-c', 'user.name=Fictional Builder', '-c', 'user.email=builder@example.invalid',
                 'commit', '-qm', 'Fictional filter setup')
        marker.unlink(missing_ok=True)
        excluded = self.root / '.env'
        previous = excluded.read_bytes()
        excluded.write_bytes(b'X' * len(previous))
        manifests = self.build()
        self.assertTrue(manifests['static']['git_dirty'])
        self.assertFalse(marker.exists(), 'The builder must not execute an excluded-file clean filter')
        self.assertEqual(excluded.read_bytes(), b'X' * len(previous))

    def test_source_symlinks_and_unlisted_reads_are_refused(self):
        sentinel = self.base / 'private-sentinel.txt'
        sentinel.write_bytes(b'UNREAD-FICTIONAL-PRIVATE-SENTINEL')
        source = self.root / 'index.html'
        source.unlink()
        source.symlink_to(sentinel)
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.output.exists())
        source.unlink()
        source.write_bytes(b'Fictional index\n')
        server = self.root / 'server'
        moved = self.root / 'real-server'
        server.rename(moved)
        server.symlink_to(moved, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.build()
        root_fd = bundle.open_directory(self.root)
        try:
            with self.assertRaisesRegex(ValueError, 'allowlist'):
                bundle.read_source_once(root_fd, '.env')
        finally:
            os.close(root_fd)
        self.assertEqual(sentinel.read_bytes(), b'UNREAD-FICTIONAL-PRIVATE-SENTINEL')

    def test_output_symlinks_and_nonprivate_modes_are_refused_without_overwrite(self):
        target = self.base / 'untouched-private-target'
        target.mkdir(mode=0o700)
        sentinel = target / 'sentinel.txt'
        sentinel.write_bytes(b'Fictional owner file')
        self.output.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(list(target.iterdir()), [sentinel])
        self.output.unlink()
        self.output.mkdir(mode=0o755)
        self.output.chmod(0o755)
        with self.assertRaisesRegex(ValueError, '0700'):
            self.build()
        self.assertEqual(list(self.output.iterdir()), [])
        self.output.chmod(0o700)
        self.build()
        archive = self.output / 'family-static.zip'
        previous_archive = archive.read_bytes()
        archive.chmod(0o644)
        with self.assertRaisesRegex(ValueError, '0600'):
            self.build()
        self.assertEqual(archive.read_bytes(), previous_archive)
        archive.chmod(0o600)
        archive.unlink()
        archive.symlink_to(sentinel)
        with self.assertRaises(ValueError):
            self.build()
        self.assertTrue(archive.is_symlink())
        self.assertEqual(sentinel.read_bytes(), b'Fictional owner file')

    def test_stale_incomplete_or_unexpected_output_never_overwrites_existing_files(self):
        self.build()
        previous = self.output_bytes()
        (self.root / 'index.html').write_bytes(b'Fictional changed build\n')
        with self.assertRaisesRegex(ValueError, 'different build'):
            self.build()
        self.assertEqual(self.output_bytes(), previous)
        extra = self.output / 'unexpected-fictional-PRIVATE.json'
        extra.write_bytes(b'Keep fictional owner file')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            self.build()
        self.assertEqual(extra.read_bytes(), b'Keep fictional owner file')
        extra.unlink()
        removed = self.output / 'family-operator.MANIFEST.json'
        removed.unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.build()
        self.assertFalse(removed.exists())
        for name, payload in previous.items():
            if name != removed.name:
                self.assertEqual((self.output / name).read_bytes(), payload)

    def test_output_inside_checkout_and_symlink_parent_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'outside'):
            self.build(self.root / 'release-output')
        self.assertFalse((self.root / 'release-output').exists())
        parent = self.base / 'symlink-parent'
        parent.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.build(parent / 'forbidden-output')
        self.assertFalse((self.base / 'forbidden-output').exists())


if __name__ == '__main__':
    unittest.main()
