"""One-file code-only patch; actual PowerShell execution is tested separately."""
from __future__ import annotations

import base64
import hashlib
import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('private_windows_patch_builder',
    ROOT / 'tools/build_windows_verification_launcher_patch.py')
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)


def sha(data):
    return hashlib.sha256(data).hexdigest()


class WindowsLauncherPatch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fictional-windows-launcher-patch-')
        self.root = Path(self.temp.name)
        self.output = self.root / 'diagnostic-code-only.zip'

    def tearDown(self):
        self.temp.cleanup()

    def decode_patch(self):
        report = BUILDER.build(output=self.output)
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.namelist(), [BUILDER.LAUNCHER])
            launcher = archive.read(BUILDER.LAUNCHER)
        encoded = re.search(rb'-EncodedCommand ([A-Za-z0-9+/=]+)', launcher).group(1)
        return report, launcher, base64.b64decode(encoded).decode('utf-16le')

    def test_exactly_one_cmd_and_diagnostic_report_without_private_or_fix_claim(self):
        report, launcher, loader = self.decode_patch()
        self.assertEqual(report['outcome'], 'diagnostic-launcher-only')
        self.assertEqual(report['file_count'], 1)
        self.assertEqual(report['bytes'], self.output.stat().st_size)
        self.assertEqual(report['sha256'], sha(self.output.read_bytes()))
        self.assertEqual(report['launcher_sha256'], sha(launcher))
        self.assertEqual(report['native_owner_windows_acceptance'], 'pending')
        for flag in ('contains_private_data', 'application_payload_changed', 'reads_owner_inputs',
                     'root_cause_confirmed', 'fix_confirmed', 'production_changed', 'main_changed'):
            self.assertFalse(report[flag])
        self.assertTrue(report['original_archive_unchanged'])
        with zipfile.ZipFile(self.output) as archive:
            self.assertEqual(archive.getinfo(BUILDER.LAUNCHER).external_attr >> 16, 0o100644)
        self.assertNotIn('__WINDOWS_', launcher.decode() + loader)

    def test_loader_is_current_shared_source_bound_to_original_published_preflight(self):
        _, launcher, loader = self.decode_patch()
        with zipfile.ZipFile(BUILDER.ORIGINAL_ARCHIVE) as original:
            preflight = original.read(BUILDER.SHARED.PREFLIGHT)
        self.assertEqual(sha(preflight), BUILDER.ORIGINAL_PREFLIGHT_SHA256)
        expected = BUILDER.SHARED.PREFLIGHT_LOADER.replace('__WINDOWS_PREFLIGHT_SHA256__', sha(preflight))
        self.assertEqual(loader, expected)
        self.assertIn('[IO.FileShare]::Read', loader)
        self.assertNotRegex(loader + launcher.decode(), r'(?i)-ExecutionPolicy\s+Bypass|Invoke-Expression')
        self.assertLessEqual(max(map(len, launcher.splitlines())), 7000)
        self.assertNotIn(b'\n', launcher.replace(b'\r\n', b''))

    def test_source_archive_unchanged_and_patch_build_is_deterministic(self):
        original_digest = sha(BUILDER.ORIGINAL_ARCHIVE.read_bytes())
        first = BUILDER.build(output=self.output)
        other = self.root / 'same-code.zip'
        second = BUILDER.build(output=other)
        self.assertEqual(self.output.read_bytes(), other.read_bytes())
        self.assertEqual(first, second)
        self.assertEqual(sha(BUILDER.ORIGINAL_ARCHIVE.read_bytes()), original_digest)
        self.assertEqual(original_digest, BUILDER.ORIGINAL_SHA256)

    def test_changed_original_archive_refused_before_output(self):
        altered = self.root / 'changed.zip'
        altered.write_bytes(BUILDER.ORIGINAL_ARCHIVE.read_bytes() + b'FICTIONAL-CHANGE')
        with patch.object(BUILDER, 'ORIGINAL_ARCHIVE', altered):
            with self.assertRaisesRegex(ValueError, 'archive pin'):
                BUILDER.build(output=self.output)
        self.assertFalse(self.output.exists())

    def test_existing_output_and_linked_parent_refused_without_overwrite(self):
        self.output.write_bytes(b'FICTIONAL-PRESERVED')
        with self.assertRaisesRegex(ValueError, 'new ZIP'):
            BUILDER.build(output=self.output)
        self.assertEqual(self.output.read_bytes(), b'FICTIONAL-PRESERVED')
        outside = self.root / 'outside'
        outside.mkdir()
        linked = self.root / 'linked'
        linked.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'link forbidden'):
            BUILDER.build(output=linked / 'patch.zip')
        self.assertEqual(list(outside.iterdir()), [])

    def test_command_limit_refuses_oversized_shared_loader_without_output(self):
        with patch.object(BUILDER.SHARED, 'PREFLIGHT_LOADER',
                          BUILDER.SHARED.PREFLIGHT_LOADER + '\n#' + 'x' * 10000):
            with self.assertRaisesRegex(ValueError, 'command length'):
                BUILDER.build(output=self.output)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
