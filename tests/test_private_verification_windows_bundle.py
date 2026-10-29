"""Actual closure/build guards; native Windows launcher acceptance is separate."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('private_windows_builder', ROOT / 'tools/build_private_verification_windows_bundle.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class WindowsVerificationBundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if cls.node is None:
            raise unittest.SkipTest('Node is required for actual closure checks')
        cls.shared = tempfile.TemporaryDirectory(prefix='fictional-windows-verifier-')
        cls.shared_root = Path(cls.shared.name)
        cls.archive = cls.shared_root / 'code-only.zip'
        cls.report = BUILDER.build(output=cls.archive)
        cls.reference = cls.shared_root / 'reference'
        cls.reference.mkdir()
        with zipfile.ZipFile(cls.archive) as archive:
            archive.extractall(cls.reference)
        cls.bootstrap = cls.reference / 'app/windows-bootstrap.cjs'

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fictional-windows-closure-')
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle'
        shutil.copytree(self.reference, self.bundle)

    def tearDown(self):
        self.temp.cleanup()

    def verify(self, *, pin=None, forbid_private=False, root=None):
        script = r"""
const fs=require('node:fs/promises');
const bootstrap=require(process.argv[1]);
if(process.argv[4]==='guard'){
  const open=fs.open,readdir=fs.readdir;
  fs.open=async function(filename,...args){if(String(filename).includes('PRIVATE-'))throw Error('MUST_NOT_READ');return open.call(this,filename,...args);};
  fs.readdir=async function(filename,...args){if(String(filename).includes('PRIVATE-'))throw Error('MUST_NOT_TRAVERSE');return readdir.call(this,filename,...args);};
}
bootstrap.verifyBundle(process.argv[2],process.argv[3]||undefined).then(()=>{process.exitCode=0;}).catch(()=>{process.exitCode=7;});
"""
        environment = os.environ.copy()
        for name in ('NODE_OPTIONS', 'NODE_PATH'):
            environment.pop(name, None)
        result = subprocess.run([self.node, '--no-global-search-paths', '-e', script,
            str(self.bootstrap), str(root or self.bundle), pin or '', 'guard' if forbid_private else ''],
            capture_output=True, text=True, env=environment, timeout=45)
        self.assertEqual(result.stdout, '', 'bootstrap leaked output')
        self.assertEqual(result.stderr, '', 'bootstrap leaked exception')
        return result.returncode

    def test_self_contained_allowlist_and_three_stage_trust_chain(self):
        self.assertEqual(self.verify(), 0)
        self.assertFalse(self.report['contains_private_data'])
        self.assertFalse(self.report['native_owner_windows_passed'])
        self.assertEqual(self.report['native_owner_windows_acceptance'], 'pending')
        self.assertFalse(self.report['production_changed'])
        self.assertGreater(self.report['bytes'], 30*1024*1024)
        self.assertLess(self.report['bytes'], 45*1024*1024)
        raw = (self.bundle / 'MANIFEST.json').read_bytes()
        bootstrap = (self.bundle / 'app/windows-bootstrap.cjs').read_bytes()
        preflight = (self.bundle / BUILDER.PREFLIGHT).read_bytes()
        launcher = (self.bundle / BUILDER.LAUNCHER).read_text()
        command = re.search(r'-EncodedCommand ([A-Za-z0-9+/=]+)', launcher).group(1)
        loader = base64.b64decode(command).decode('utf-16le')
        self.assertIn(sha(raw).encode(), bootstrap)
        self.assertIn(sha(raw).encode(), preflight)
        self.assertIn(sha(bootstrap).encode(), preflight)
        self.assertIn(sha(preflight), loader)
        self.assertLess(max(map(len, launcher.splitlines())), 7000)
        self.assertNotIn('ExecutionPolicy', loader)
        self.assertNotRegex(launcher, r'(?i)-ExecutionPolicy\s+Bypass|Invoke-Expression')
        self.assertIn('[IO.FileShare]::Read', loader)
        self.assertIn('[IO.FileShare]::Read', preflight.decode())
        self.assertNotIn('__WINDOWS_', launcher + preflight.decode() + bootstrap.decode())
        with zipfile.ZipFile(self.archive) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), self.report['file_count'])
            self.assertTrue(all('PRIVATE-' not in n and 'capture.cjs' not in n and 'classic-level' not in n for n in names))
            self.assertEqual(sha(archive.read('runtime/node.exe')), BUILDER.NODE_SHA256)
            self.assertEqual(len(archive.read('runtime/node.exe')), BUILDER.NODE_BYTES)

    def test_every_payload_hash_checked_before_import(self):
        manifest = json.loads((self.bundle / 'MANIFEST.json').read_bytes())
        for item in manifest['files']:
            with self.subTest(name=item['path']):
                target = self.bundle / item['path']
                original = target.read_bytes()
                target.write_bytes(original + b'\nFICTIONAL-TAMPER-MUST-NOT-EXECUTE')
                self.assertEqual(self.verify(), 7)
                target.write_bytes(original)

    def test_manifest_tamper_and_missing_trust_root_fail(self):
        target = self.bundle / 'MANIFEST.json'
        original = target.read_bytes()
        target.write_bytes(original + b' ')
        self.assertEqual(self.verify(), 7)
        target.write_bytes(original)
        for name in ('Start Windows verification.cmd', 'Start Windows verification.ps1', 'app/windows-bootstrap.cjs'):
            with self.subTest(name=name):
                target = self.bundle / name
                data = target.read_bytes()
                target.unlink()
                self.assertEqual(self.verify(), 7)
                target.write_bytes(data)

    def test_private_result_folder_metadata_only_never_read(self):
        folder = self.bundle / 'PRIVATE-verification-fictional'
        folder.mkdir()
        (folder / 'private.json').write_text('FICTIONAL_PRIVATE_NEVER_OPEN')
        folder.chmod(0)
        try:
            self.assertEqual(self.verify(forbid_private=True), 0)
        finally:
            folder.chmod(0o700)

    def test_unknown_shadow_case_collision_and_private_file_fail(self):
        for name in ('app/package.json', 'app/node_modules/koffi/build/win32_x64/koffi.node',
                     'app/core.js', 'app/node_modules/@koromix/koffi-win32-x64/index.cjs',
                     'runtime/node_modules/shadow.cjs', 'unknown.json', 'PRIVATE-verification-fictional'):
            with self.subTest(name=name):
                target = self.bundle / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('FICTIONAL_NEVER_EXECUTE')
                self.assertEqual(self.verify(), 7)
                target.unlink()
                while target.parent != self.bundle and not any(target.parent.iterdir()):
                    target.parent.rmdir()
                    target = target.parent
        (self.bundle / 'readme_windows_ru.txt').write_text('case collision')
        self.assertEqual(self.verify(), 7)

    def test_leaf_directory_root_symlinks_and_hardlinks_fail(self):
        target = self.bundle / 'app/core.cjs'
        original = target.read_bytes()
        outside = self.root / 'other.cjs'
        outside.write_bytes(original)
        target.unlink()
        target.symlink_to(outside)
        self.assertEqual(self.verify(), 7)
        target.unlink()
        os.link(outside, target)
        self.assertEqual(self.verify(), 7)
        target.unlink()
        target.write_bytes(original)
        linked_root = self.root / 'linked'
        linked_root.symlink_to(self.bundle, target_is_directory=True)
        self.assertEqual(self.verify(root=linked_root), 7)
        asset = self.bundle / 'app/pglite'
        moved = self.root / 'moved-assets'
        asset.rename(moved)
        asset.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.verify(), 7)

    def test_manifest_windows_component_and_coverage_guards(self):
        target = self.bundle / 'MANIFEST.json'
        original = target.read_bytes()
        for name in ('app/../core.cjs', 'app//core.cjs', 'app/core.cjs ', 'app/NUL.txt',
                     'app/COn.json', 'app/core.cjs:stream', 'app\\core.cjs', '/core.cjs'):
            with self.subTest(name=name):
                value = json.loads(original)
                value['files'][0]['path'] = name
                raw = json.dumps(value).encode()
                target.write_bytes(raw)
                self.assertEqual(self.verify(pin=sha(raw)), 7)
        target.write_bytes(original)
        value = json.loads(original)
        value['files'].pop()
        raw = json.dumps(value).encode()
        target.write_bytes(raw)
        self.assertEqual(self.verify(pin=sha(raw)), 7)

    def test_builder_pins_old_archive_and_rejects_existing_or_linked_output(self):
        with self.assertRaisesRegex(ValueError, 'new ZIP'):
            BUILDER.build(output=self.archive)
        altered = self.root / 'altered.zip'
        altered.write_bytes(BUILDER.ORIGINAL_ARCHIVE.read_bytes() + b'fictional-change')
        with patch.object(BUILDER, 'ORIGINAL_ARCHIVE', altered):
            with self.assertRaisesRegex(ValueError, 'archive pin'):
                BUILDER.build(output=self.root / 'not-built.zip')
        linked = self.root / 'linked-output'
        outside = self.root / 'outside-output'
        outside.mkdir()
        linked.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'link forbidden'):
            BUILDER.build(output=linked / 'no.zip')

    def test_runtime_unconfigured_entry_fails_with_fixed_code_without_native_load(self):
        result = subprocess.run([self.node, '--no-global-search-paths', str(self.bootstrap)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, 'Результат: failed\nКоды: verification-runtime\n')
        self.assertEqual(result.stderr, '')


if __name__ == '__main__':
    unittest.main()
