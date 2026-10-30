"""Candidate downloads must have a small, reproducible, explicit public scope."""
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import stat
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('build_accounts_bundle', ROOT / 'tools/build_accounts_bundle.py')
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class PublicAccountsBundle(unittest.TestCase):
    def test_exact_public_allowlist_manifest_and_no_private_files(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'candidate.zip'
            bundle.build(output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(bundle.SOURCE_FILES) | set(bundle.GENERATED_FILES))
                manifest = json.loads(archive.read('MANIFEST.json'))
                self.assertEqual(set(manifest['files']), set(bundle.SOURCE_FILES) | {'README_RU.md'})
                for name, digest in manifest['files'].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
                for name in bundle.SOURCE_FILES:
                    self.assertEqual(archive.read(name), (ROOT / name).read_bytes())
                for info in archive.infolist():
                    self.assertFalse(PurePosixPath(info.filename).is_absolute())
                    self.assertNotIn('..', PurePosixPath(info.filename).parts)
                    self.assertTrue(stat.S_ISREG(info.external_attr >> 16))
                    self.assertEqual(info.date_time, bundle.ZIP_TIMESTAMP)
                self.assertNotIn('index.html', archive.namelist())
                self.assertFalse(any('.env' in name or 'backup' in name or name.startswith('tests/') for name in archive.namelist()))
                self.assertIn('не опубликованный сервис', archive.read('README_RU.md').decode())

    def test_repeated_build_is_identical_and_private_markers_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'candidate.zip'
            bundle.build(output)
            first = output.read_bytes()
            bundle.build(output)
            self.assertEqual(first, output.read_bytes())
        for credential in (b'sb_secret_this_is_fake_but_must_not_ship',
                           b'-----BEGIN PRIVATE KEY-----',
                           b'eyJfakeheader123456.fakepayload123456.fakesignature123456'):
            with self.assertRaises(ValueError):
                bundle.validate_public_payload({'public/accounts.js': credential})

    def test_source_and_output_symlinks_are_rejected_without_overwriting_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'sources'
            for name in bundle.SOURCE_FILES:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fake source')
            private = Path(temp) / 'private.txt'
            private.write_bytes(b'private sentinel')
            source = root / bundle.SOURCE_FILES[0]
            source.unlink()
            source.symlink_to(private)
            with self.assertRaises(ValueError):
                bundle.build(Path(temp) / 'candidate.zip', root=root)
            source.unlink()
            source.write_bytes(b'fake source')
            output = Path(temp) / 'candidate.zip'
            output.symlink_to(private)
            with self.assertRaises(ValueError):
                bundle.build(output, root=root)
            self.assertEqual(private.read_bytes(), b'private sentinel')


if __name__ == '__main__':
    unittest.main()
