"""Code-only addon trust-chain tests; native owner-Mac acceptance is separate."""
from __future__ import annotations

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
SPEC = importlib.util.spec_from_file_location('private_addon_builder', ROOT / 'tools/build_private_verification_macos_bundle.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
MARKER = 'FICTIONAL_OWNER_PRIVATE_CONTENT_MUST_NOT_BE_READ'
OLD_REQUIRED = ('Start Mac backup.command', 'README_MAC_RU.txt', 'BUILD.json',
                'app/mac-bootstrap.cjs', 'app/mac-main.cjs', 'app/macos.cjs',
                'app/capture.cjs', 'app/integrity.cjs', 'runtime/arm64/node',
                'runtime/arm64/NODE-LICENSE.txt', 'runtime/x64/node', 'runtime/x64/NODE-LICENSE.txt')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def copy_sources(destination):
    for name in (*BUILDER.APP, BUILDER.BOOTSTRAP, BUILDER.LAUNCHER, 'README_MAC_RU.txt'):
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(BUILDER.SOURCE / name, target)


class PrivateVerificationBundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.node = shutil.which('node')
        if cls.node is None:
            raise unittest.SkipTest('Node is needed to execute the actual bootstrap checks')
        cls.shared = tempfile.TemporaryDirectory(prefix='fictional-addon-source-')
        cls.shared_root = Path(cls.shared.name)
        cls.archive = cls.shared_root / 'code-only.zip'
        cls.receipt = BUILDER.build(output=cls.archive)
        cls.reference = cls.shared_root / 'reference'
        cls.reference.mkdir()
        with zipfile.ZipFile(cls.archive) as archive:
            archive.extractall(cls.reference)
        cls.bootstrap = cls.reference / 'app/mac-bootstrap.cjs'

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fictional-addon-check-')
        self.root = Path(self.temp.name)
        self.addon = self.root / 'addon'
        shutil.copytree(self.reference, self.addon)
        self.old = self.root / 'old-helper'
        for name in OLD_REQUIRED:
            target = self.old / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(('fictional-code-only:' + name).encode())
        files = [{'path': name, 'bytes': (self.old / name).stat().st_size,
                  'sha256': sha((self.old / name).read_bytes())} for name in OLD_REQUIRED]
        self.old_manifest = {'format': 'marichevy-offline-queue-macos-bundle-v1', 'files': files}
        self.old_pin = self.write_manifest(self.old, self.old_manifest)

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self, root, value):
        raw = json.dumps(value, ensure_ascii=True).encode()
        (root / 'MANIFEST.json').write_bytes(raw)
        return sha(raw)

    def verify(self, folder, kind='addon', pin=None, *, forbid_private=False):
        code = r"""
const fs=require('node:fs/promises');
const bootstrap=require(process.argv[1]);
if(process.argv[5]==='guard'){
  const open=fs.open;
  fs.open=async function(filename,...args){
    if(String(filename).includes('PRIVATE-')||String(filename).endsWith('/.DS_Store'))throw Error('MUST_NOT_READ');
    return open.call(this,filename,...args);
  };
}
const action=process.argv[3]==='old'?bootstrap.verifyOldBundle:bootstrap.verifyAddon;
action(process.argv[2],process.argv[4]||undefined).then(()=>{process.exitCode=0;}).catch(()=>{process.exitCode=7;});
"""
        environment = os.environ.copy()
        for key in ('NODE_OPTIONS', 'NODE_PATH'):
            environment.pop(key, None)
        result = subprocess.run([self.node, '--no-global-search-paths', '-e', code,
                                 str(self.bootstrap), str(folder), kind, pin or '', 'guard' if forbid_private else ''],
                                capture_output=True, text=True, env=environment, timeout=45)
        self.assertEqual(result.stdout, '', 'bootstrap-disclosed-output')
        self.assertEqual(result.stderr, '', 'bootstrap-disclosed-error')
        return result.returncode

    def test_code_only_build_manifest_closure_and_trust_root_chain(self):
        self.assertEqual(self.verify(self.addon), 0)
        self.assertEqual(self.receipt['file_count'], 16)
        self.assertLess(self.receipt['bytes'], 6 * 1024 * 1024)
        self.assertFalse(self.receipt['contains_private_data'])
        self.assertFalse(self.receipt['native_owner_mac_passed'])
        self.assertEqual(self.receipt['native_owner_mac_acceptance'], 'pending')
        manifest_raw = (self.addon / 'MANIFEST.json').read_bytes()
        bootstrap = (self.addon / 'app/mac-bootstrap.cjs').read_bytes()
        launcher = (self.addon / BUILDER.LAUNCHER).read_bytes()
        self.assertIn(sha(manifest_raw).encode(), bootstrap)
        self.assertIn(sha(bootstrap).encode(), launcher)
        self.assertNotIn(b'__ADDON_', bootstrap + launcher)
        with zipfile.ZipFile(self.archive) as archive:
            names = archive.namelist()
            self.assertEqual(set(names), set(['BUILD.json', 'MANIFEST.json', 'README_MAC_RU.txt', BUILDER.LAUNCHER,
                                              'app/mac-bootstrap.cjs'] + ['app/' + n for n in BUILDER.APP]))
            self.assertEqual(archive.getinfo(BUILDER.LAUNCHER).external_attr >> 16, 0o100755)
            self.assertTrue(all('PRIVATE-' not in n and 'tests/' not in n and 'runtime/' not in n for n in names))
            for name in names:
                self.assertEqual(archive.read(name), (self.addon / name).read_bytes())

    def test_every_payload_kind_is_hash_checked_before_import(self):
        for name in ('app/core.cjs', 'app/mac-main.cjs', 'app/local-restore.cjs', 'app/owner-export.cjs',
                     'app/owner-export.sql', 'app/sql-sources.json', 'app/pglite/index.cjs',
                     'app/pglite/pglite.wasm', 'app/pglite/pglite.data', 'app/pglite/package.json',
                     'app/pglite/LICENSE', 'README_MAC_RU.txt', 'BUILD.json'):
            with self.subTest(name=name):
                target = self.addon / name
                original = target.read_bytes()
                target.write_bytes(original + b'\n// FICTIONAL_TAMPERING_MUST_NOT_EXECUTE')
                self.assertEqual(self.verify(self.addon), 7)
                target.write_bytes(original)

    def test_bootstrap_tampering_breaks_shell_pin_and_manifest_tampering_breaks_bootstrap_pin(self):
        bootstrap = self.addon / 'app/mac-bootstrap.cjs'
        original = bootstrap.read_bytes()
        launcher = (self.addon / BUILDER.LAUNCHER).read_text()
        self.assertTrue(launcher.startswith('#!/bin/bash -p\n'))
        fixed = re.search(r'!= ([0-9a-f]{64}) \]', launcher).group(1)
        self.assertEqual(sha(original), fixed)
        bootstrap.write_bytes(original + b'\n// tampered trust root')
        self.assertNotEqual(sha(bootstrap.read_bytes()), fixed)
        bootstrap.write_bytes(original)
        manifest = self.addon / 'MANIFEST.json'
        manifest.write_bytes(manifest.read_bytes() + b' ')
        self.assertEqual(self.verify(self.addon), 7)

    def test_unknown_shadow_metadata_and_case_collisions_fail(self):
        for name in ('app/node_modules/shadow/index.cjs', 'app/package.json', 'app/core.js',
                     'app/pglite/index.js', 'app/.DS_Store', 'app/._core.cjs',
                     'runtime/arm64/node', 'unknown.json', '._MANIFEST.json', 'App/foreign.cjs'):
            with self.subTest(name=name):
                target = self.addon / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(MARKER)
                self.assertEqual(self.verify(self.addon), 7)
                target.unlink()
                while target.parent != self.addon and not any(target.parent.iterdir()):
                    parent = target.parent
                    parent.rmdir()
                    target = parent
        collision = self.addon / 'readme_mac_ru.txt'
        collision.write_text('case collision')
        self.assertEqual(self.verify(self.addon), 7)

    def test_root_ds_store_and_private_output_are_not_read_or_traversed(self):
        for folder, kind, pin in ((self.addon, 'addon', None), (self.old, 'old', self.old_pin)):
            (folder / '.DS_Store').write_text(MARKER)
            private = folder / 'PRIVATE-verification-fictional'
            private.mkdir()
            (private / 'never-read.json').write_text(MARKER)
            private.chmod(0)
            try:
                self.assertEqual(self.verify(folder, kind, pin, forbid_private=True), 0)
            finally:
                private.chmod(0o700)
            (folder / '.DS_Store').write_bytes(b'x' * (1024 * 1024 + 1))
            self.assertEqual(self.verify(folder, kind, pin), 7)

    def test_private_output_name_must_be_a_nonlinked_directory(self):
        target = self.addon / 'PRIVATE-backup-fictional'
        target.write_text(MARKER)
        self.assertEqual(self.verify(self.addon), 7)
        target.unlink()
        outside = self.root / 'outside-private'
        outside.mkdir()
        target.symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.verify(self.addon), 7)

    def test_file_parent_root_symlinks_and_hardlinks_fail(self):
        code = self.addon / 'app/core.cjs'
        original = code.read_bytes()
        outside = self.root / 'outside.cjs'
        outside.write_bytes(original)
        code.unlink()
        code.symlink_to(outside)
        self.assertEqual(self.verify(self.addon), 7)
        code.unlink()
        os.link(outside, code)
        self.assertEqual(self.verify(self.addon), 7)
        code.unlink()
        code.write_bytes(original)
        link = self.root / 'alias'
        link.symlink_to(self.addon, target_is_directory=True)
        self.assertEqual(self.verify(link), 7)
        assets = self.addon / 'app/pglite'
        moved = self.root / 'moved-assets'
        assets.rename(moved)
        assets.symlink_to(moved, target_is_directory=True)
        self.assertEqual(self.verify(self.addon), 7)

    def test_traversal_absolute_casefold_duplicate_missing_and_oversized_manifests_fail(self):
        raw = (self.addon / 'MANIFEST.json').read_bytes()
        for name in ('../outside', '/outside', 'app/../outside', 'app//core.cjs', 'app\\core.cjs',
                     'app/control\nname', 'PRIVATE-verification-foreign/private.json'):
            value = json.loads(raw)
            value['files'][0]['path'] = name
            pin = self.write_manifest(self.addon, value)
            self.assertEqual(self.verify(self.addon, pin=pin), 7)
        for mutate in (lambda v: v['files'].append(v['files'][0]), lambda v: v['files'].pop(),
                       lambda v: v['files'][0].update(bytes=True), lambda v: v['files'][0].update(bytes=2 ** 60),
                       lambda v: v['files'][0].update(sha256='z' * 64),
                       lambda v: v['files'][0].update(extra='unexpected')):
            value = json.loads(raw)
            mutate(value)
            pin = self.write_manifest(self.addon, value)
            self.assertEqual(self.verify(self.addon, pin=pin), 7)
        (self.addon / 'MANIFEST.json').write_bytes(b'x' * (2 * 1024 * 1024 + 1))
        self.assertEqual(self.verify(self.addon), 7)

    def test_old_bundle_pinned_manifest_changed_file_missing_file_and_shadow_fail(self):
        self.assertEqual(self.verify(self.old, 'old', self.old_pin), 0)
        # A synthetic old closure can never satisfy the real pinned manifest.
        self.assertEqual(self.verify(self.old, 'old'), 7)
        target = self.old / 'app/macos.cjs'
        original = target.read_bytes()
        target.write_bytes(original + b'tamper')
        self.assertEqual(self.verify(self.old, 'old', self.old_pin), 7)
        target.write_bytes(original)
        target.unlink()
        self.assertEqual(self.verify(self.old, 'old', self.old_pin), 7)
        target.write_bytes(original)
        (self.old / 'app/node_modules').mkdir()
        (self.old / 'app/node_modules/shadow.cjs').write_text(MARKER)
        self.assertEqual(self.verify(self.old, 'old', self.old_pin), 7)

    def test_actual_original_code_zip_matches_fixed_manifest(self):
        original = ROOT / 'preview/mac-private-backup-helper-v95.zip'
        self.assertTrue(original.is_file(), 'the reviewed existing helper ZIP is required')
        folder = self.root / 'actual-code-only-original'
        folder.mkdir()
        with zipfile.ZipFile(original) as archive:
            self.assertEqual(sha(archive.read('MANIFEST.json')), BUILDER.OLD_MANIFEST_SHA256)
            self.assertIsNone(archive.testzip())
            archive.extractall(folder)
        self.assertEqual(self.verify(folder, 'old'), 0)

    def test_builder_never_discovers_private_files_and_preserves_existing_archive(self):
        source = self.root / 'code-source'
        copy_sources(source)
        private = source / 'PRIVATE-backup-fixture'
        private.mkdir()
        (private / 'owner.json').write_text(MARKER)
        private.chmod(0)
        output = self.root / 'new-code-only.zip'
        try:
            with patch.object(BUILDER, 'SOURCE', source):
                receipt = BUILDER.build(output=output)
            with zipfile.ZipFile(output) as archive:
                self.assertTrue(all('PRIVATE-' not in name for name in archive.namelist()))
                for name in archive.namelist():
                    self.assertNotIn(MARKER.encode(), archive.read(name))
            self.assertEqual(receipt['file_count'], 16)
            before = output.read_bytes()
            with self.assertRaisesRegex(ValueError, 'new ZIP'):
                BUILDER.build(output=output)
            self.assertEqual(output.read_bytes(), before)
        finally:
            private.chmod(0o700)

    def test_builder_refuses_source_links_hardlinks_and_changed_pinned_assets(self):
        source = self.root / 'code-source'
        copy_sources(source)
        output = self.root / 'must-not-exist.zip'
        target = source / 'core.cjs'
        original = target.read_bytes()
        outside = self.root / 'outside.cjs'
        outside.write_bytes(original)
        target.unlink()
        target.symlink_to(outside)
        with patch.object(BUILDER, 'SOURCE', source):
            with self.assertRaisesRegex(ValueError, 'link forbidden'):
                BUILDER.build(output=output)
        target.unlink()
        os.link(outside, target)
        with patch.object(BUILDER, 'SOURCE', source):
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                BUILDER.build(output=output)
        target.unlink()
        target.write_bytes(original)
        asset = source / 'pglite/pglite.wasm'
        asset.write_bytes(asset.read_bytes() + b'tampered')
        with patch.object(BUILDER, 'SOURCE', source):
            with self.assertRaisesRegex(ValueError, 'asset mismatch'):
                BUILDER.build(output=output)
        self.assertFalse(output.exists())

    def test_launcher_offline_pins_clean_environment_literal_read_and_shell_syntax(self):
        launcher = (self.addon / BUILDER.LAUNCHER).read_text()
        self.assertIn('/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin', launcher)
        self.assertIn('--no-global-search-paths', launcher)
        self.assertNotIn('IFS= read -r task_bundle', launcher)
        self.assertIn('choose folder with prompt', launcher)
        self.assertIn('task_helper_folder_valid', launcher)
        self.assertIn('verification-helper-selection-cancelled', launcher)
        self.assertIn('IFS= read -r task_end', launcher)
        self.assertIn('runtime/$task_arch/node', launcher)
        self.assertEqual(launcher.count('/usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin /usr/bin/shasum'), 2)
        self.assertNotIn('task_parent/Start Mac backup.command', launcher)
        for pin in BUILDER.NODE_PINS.values():
            self.assertIn(pin, launcher)
        for forbidden in ('curl', 'wget', 'npm install', 'sudo', 'xattr', 'spctl', 'allow pasting', 'eval '):
            self.assertNotIn(forbidden, launcher.lower())
        result = subprocess.run(['bash', '-n', str(self.addon / BUILDER.LAUNCHER)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, b'')
        bootstrap = self.bootstrap.read_text()
        imports = bootstrap.index("const main=require('./mac-main.cjs')")
        self.assertLess(bootstrap.index('await verifyOldBundle(oldBundleRoot);'), imports)
        self.assertLess(bootstrap.index('await verifyAddon(addonRoot);'), imports)


if __name__ == '__main__':
    unittest.main()
