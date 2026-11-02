"""Code-only Mac ZIP verification; no native Darwin execution is claimed."""
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('mac_bundle', ROOT / 'tools/build_offline_queue_macos_bundle.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def thin(cpu):
    data = bytearray(64)
    data[:4] = b'\xcf\xfa\xed\xfe'
    struct.pack_into('<I', data, 4, cpu)
    return bytes(data)


def fat():
    data = bytearray(176)
    data[:4] = b'\xca\xfe\xba\xbe'
    struct.pack_into('>I', data, 4, 2)
    for index, cpu in enumerate(builder.CPUS.values()):
        offset = 48 + index * 64
        struct.pack_into('>IIIII', data, 8 + index * 20, cpu, 0, offset, 64, 0)
        data[offset:offset + 64] = thin(cpu)
    return bytes(data)


class MacBundle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fictional-macos-bundle-')
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        for name in builder.APP + builder.ROOT_FILES:
            origin = builder.SOURCE / name
            if origin.exists():
                shutil.copyfile(origin, self.source / name)
            else:
                (self.source / name).write_text('// fictional code-only placeholder\n')
        self.dependencies = {
            'classic-level/prebuilds/darwin-x64+arm64/classic-level.node': fat(),
            '@koromix/koffi-darwin-arm64/darwin_arm64/koffi.node': thin(builder.CPUS['arm64']),
            '@koromix/koffi-darwin-x64/darwin_x64/koffi.node': thin(builder.CPUS['x64']),
        }
        inventory = {'format': 'marichevy-macos-dependencies-v1',
                     'lockfile_sha256': builder.sha((self.source / 'package-lock.json').read_bytes()),
                     'files': {k: {'bytes': len(v), 'sha256': builder.sha(v)}
                               for k, v in self.dependencies.items()}}
        (self.source / 'dependencies-macos.inventory.json').write_text(json.dumps(inventory))
        self.runtimes = self.root / 'runtime-inputs'
        pin = {'format': 'marichevy-macos-runtime-pin-v1', 'version': 'v22.23.4', 'architectures': {}}
        for arch, cpu in builder.CPUS.items():
            directory = self.runtimes / arch
            directory.mkdir(parents=True)
            (directory / 'node').write_bytes(thin(cpu))
            license_data = b'Node.js fictional test license\n' + b'x' * 11000
            (directory / 'LICENSE').write_bytes(license_data)
            pin['architectures'][arch] = {'node_bytes': len(thin(cpu)),
                                          'node_sha256': builder.sha(thin(cpu)),
                                          'node_license_sha256': builder.sha(license_data)}
        self.pin = pin
        (self.source / 'runtime-pin-macos.json').write_text(json.dumps(pin))
        self.output = self.root / 'helper.zip'

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        with patch.object(builder, 'SOURCE', self.source), patch.object(builder, 'dependency_files', return_value=self.dependencies):
            return builder.build(deps_root=self.root / 'unused', runtimes_root=self.runtimes, output=self.output)

    def extract(self):
        self.build()
        folder = self.root / 'extracted'
        folder.mkdir()
        with zipfile.ZipFile(self.output) as archive:
            archive.extractall(folder)
        return folder

    def verify(self, folder):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for the meaningful bootstrap check')
        code = "const {verifyBundle}=require(process.argv[1]);verifyBundle(process.argv[2]).then(()=>process.exitCode=0).catch(()=>process.exitCode=7)"
        result = subprocess.run([node, '-e', code, str(ROOT / 'tools/offline_queue/mac-bootstrap.cjs'), str(folder)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')
        return result.returncode

    def test_macho_thin_universal_and_malformed(self):
        self.assertEqual(builder.macho_cpus(fat()), set(builder.CPUS.values()))
        for arch, cpu in builder.CPUS.items():
            self.assertEqual(builder.macho_cpus(thin(cpu)), {cpu})
        broken = bytearray(fat())
        struct.pack_into('>I', broken, 16, 0xFFFFFFF0)
        self.assertEqual(builder.macho_cpus(broken), set())
        self.assertEqual(builder.macho_cpus(b'MZ' + b'\0' * 100), set())
        duplicate = bytearray(fat())
        struct.pack_into('>I', duplicate, 28, builder.CPUS['arm64'])
        self.assertEqual(builder.macho_cpus(duplicate), set())

    def test_manifest_architectures_modes_and_no_private_output_reads(self):
        folder = self.extract()
        private = folder / 'PRIVATE-backup-old'
        private.mkdir()
        (private / 'fictional-owner-only.json').write_text('OWNER_ONLY_SENTINEL')
        private.chmod(0)
        try:
            self.assertEqual(self.verify(folder), 0)
        finally:
            private.chmod(0o700)
        with zipfile.ZipFile(self.output) as archive:
            for name in ('runtime/arm64/node', 'runtime/x64/node', 'Start Mac backup.command'):
                self.assertEqual(archive.getinfo(name).external_attr >> 16, 0o100755)
            self.assertEqual(archive.getinfo('app/mac-main.cjs').external_attr >> 16, 0o100644)
            self.assertNotIn('OWNER_ONLY_SENTINEL', b''.join(archive.read(n) for n in archive.namelist()).decode(errors='ignore'))
            self.assertTrue(all(not n.startswith('PRIVATE') for n in archive.namelist()))

    def test_changed_code_shadow_modules_and_duplicate_manifest_fail(self):
        folder = self.extract()
        main = folder / 'app/mac-main.cjs'
        original = main.read_bytes()
        main.write_bytes(original + b'\n// altered')
        self.assertEqual(self.verify(folder), 7)
        main.write_bytes(original)
        shadow = folder / 'app/node_modules/shadow.cjs'
        shadow.write_text('throw new Error("MUST_NOT_EXECUTE")')
        self.assertEqual(self.verify(folder), 7)
        shadow.unlink()
        manifest = folder / 'MANIFEST.json'
        value = json.loads(manifest.read_text())
        value['files'].append(value['files'][0])
        manifest.write_text(json.dumps(value))
        self.assertEqual(self.verify(folder), 7)

    def test_manifest_traversals_private_files_and_symlinks_fail(self):
        folder = self.extract()
        manifest = folder / 'MANIFEST.json'
        original = manifest.read_text()
        for name in ('../outside', '/outside', 'app/../outside', 'runtime//arm64/node',
                     'PRIVATE-backup-old/private.json', 'app/back\\slash', 'app/control\nname'):
            value = json.loads(original)
            value['files'][0]['path'] = name
            manifest.write_text(json.dumps(value))
            self.assertEqual(self.verify(folder), 7)
        manifest.write_text(original)
        main = folder / 'app/mac-main.cjs'
        target = self.root / 'outside.cjs'
        target.write_bytes(main.read_bytes())
        main.unlink()
        main.symlink_to(target)
        self.assertEqual(self.verify(folder), 7)

    def test_pinned_runtime_dependency_license_and_cpu_mismatch_fail_closed(self):
        runtime = self.runtimes / 'arm64/node'
        original = runtime.read_bytes()
        runtime.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'runtime mismatch'):
            self.build()
        self.assertFalse(self.output.exists())
        runtime.write_bytes(original)
        license_file = self.runtimes / 'arm64/LICENSE'
        license_data = license_file.read_bytes()
        license_file.write_bytes(license_data + b'changed')
        with self.assertRaisesRegex(ValueError, 'license mismatch'):
            self.build()
        license_file.write_bytes(license_data)
        runtime.write_bytes(thin(builder.CPUS['x64']))
        self.pin['architectures']['arm64']['node_sha256'] = builder.sha(runtime.read_bytes())
        (self.source / 'runtime-pin-macos.json').write_text(json.dumps(self.pin))
        with self.assertRaisesRegex(ValueError, 'runtime mismatch'):
            self.build()
        runtime.write_bytes(original)
        self.pin['architectures']['arm64']['node_sha256'] = builder.sha(original)
        (self.source / 'runtime-pin-macos.json').write_text(json.dumps(self.pin))
        self.dependencies['unexpected.js'] = b'changed'
        with self.assertRaisesRegex(ValueError, 'dependency bytes'):
            self.build()
        self.assertFalse(self.output.exists())

    def test_existing_archive_is_preserved(self):
        self.output.write_bytes(b'OLD_ARCHIVE_MUST_STAY')
        with self.assertRaisesRegex(ValueError, 'new ZIP'):
            self.build()
        self.assertEqual(self.output.read_bytes(), b'OLD_ARCHIVE_MUST_STAY')

    def test_builder_refuses_source_links_and_wrong_dependency_identity(self):
        readme = self.source / 'README_MAC_RU.txt'
        readme.unlink()
        outside = self.root / 'fictional-private.txt'
        outside.write_text('OWNER_ONLY_SENTINEL')
        readme.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.build()
        self.assertFalse(self.output.exists())
        deps = self.root / 'dependencies'
        package = deps / 'abstract-level'
        package.mkdir(parents=True)
        (package / 'package.json').write_text(json.dumps({'name': 'abstract-level', 'version': '0.0.0'}))
        with patch.object(builder, 'SOURCE', self.source), patch.object(builder, 'PACKAGES', ('abstract-level',)):
            with self.assertRaisesRegex(ValueError, 'version mismatch'):
                builder.dependency_files(deps)

    def test_launcher_offline_environment_and_syntax(self):
        launcher = (builder.SOURCE / 'Start Mac backup.command').read_text()
        self.assertIn('/usr/bin/env -i', launcher)
        self.assertIn('--no-global-search-paths', launcher)
        self.assertIn('runtime/$task_arch/node', launcher)
        self.assertIn('IFS= read -r task_end', launcher)
        for forbidden in ('curl', 'wget', 'npm install', 'sudo', 'xattr', 'spctl', 'allow pasting', 'eval ', 'osascript'):
            self.assertNotIn(forbidden, launcher.lower())
        result = subprocess.run(['bash', '-n', str(builder.SOURCE / 'Start Mac backup.command')], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
