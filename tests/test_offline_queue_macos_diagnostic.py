"""Read-only fixed-bundle diagnosis; these checks are not native Mac execution."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIAGNOSTIC = ROOT / 'tools/offline_queue/mac-diagnose.cjs'
LAUNCHER = ROOT / 'tools/offline_queue/Check Mac helper.command'
REQUIRED = ['Start Mac backup.command','README_MAC_RU.txt','BUILD.json',
            'app/mac-bootstrap.cjs','app/mac-main.cjs','app/macos.cjs','app/capture.cjs','app/integrity.cjs',
            'runtime/arm64/node','runtime/arm64/NODE-LICENSE.txt','runtime/x64/node','runtime/x64/NODE-LICENSE.txt',
            'app/node_modules/classic-level/index.js','app/node_modules/koffi/index.cjs']


class MacDiagnostic(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fictional-mac-diagnostic-')
        self.directory = Path(self.temp.name)
        self.bundle = self.directory / 'bundle'
        self.bundle.mkdir()
        files = []
        for name in REQUIRED:
            file = self.bundle / name
            file.parent.mkdir(parents=True, exist_ok=True)
            data = b'// FICTIONAL_CODE_ONLY\n'
            file.write_bytes(data)
            files.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        manifest = json.dumps({'format':'marichevy-offline-queue-macos-bundle-v1','files':files}).encode()
        (self.bundle / 'MANIFEST.json').write_bytes(manifest)
        self.manifest_sha = hashlib.sha256(manifest).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def run_diagnostic(self, *, module_error=None, runtime=None, default_manifest=False, bundle=None):
        options = {'runtime': runtime or {'platform':'darwin','arch':'arm64','version':'22.23.4'}}
        if not default_manifest:
            options['expectedManifest'] = self.manifest_sha
        script = r"""
const mod=require(process.argv[1]);
const root=process.argv[2],config=JSON.parse(process.argv[3]),moduleError=JSON.parse(process.argv[4]);
const lines=[],loaded=[];
config.output=line=>lines.push(line);
config.load=filename=>{
  const relative=require('node:path').relative(root,filename);loaded.push(relative);
  if(moduleError&&relative.endsWith(moduleError.file))throw Object.assign(new Error(moduleError.message),{code:moduleError.code});
  return {main(){throw new Error('MAIN_MUST_NEVER_BE_CALLED');}};
};
mod.diagnose(root,config).then(()=>console.log(JSON.stringify({passed:true,lines,loaded})))
 .catch(error=>console.log(JSON.stringify({passed:false,report:mod.report(error),lines,loaded})));
"""
        node = shutil.which('node')
        self.assertIsNotNone(node)
        result = subprocess.run([node,'-e',script,str(DIAGNOSTIC),str(bundle or self.bundle),
                                 json.dumps(options),json.dumps(module_error)], capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, '')
        self.assertNotIn(str(self.directory), result.stdout)
        self.assertNotIn('PRIVATE_OWNER_SENTINEL', result.stdout)
        return json.loads(result.stdout)

    def test_exact_integrity_then_imports_without_main_and_ignores_private_output(self):
        private = self.bundle / 'PRIVATE-backup-old'
        private.mkdir()
        (private / 'owner-data.json').write_text('PRIVATE_OWNER_SENTINEL')
        private.chmod(0)
        try:
            result = self.run_diagnostic()
        finally:
            private.chmod(0o700)
        self.assertTrue(result['passed'])
        self.assertEqual(result['loaded'], ['app/node_modules/classic-level','app/node_modules/koffi',
                                           'app/macos.cjs','app/integrity.cjs','app/mac-main.cjs'])
        self.assertIn('Проверка: fixed-bundle-integrity-passed', result['lines'])

    def test_runtime_and_fixed_manifest_fail_before_module_load(self):
        for runtime in ({'platform':'linux','arch':'arm64','version':'22.23.4'},
                        {'platform':'darwin','arch':'arm','version':'22.23.4'},
                        {'platform':'darwin','arch':'arm64','version':'22.23.3'}):
            result = self.run_diagnostic(runtime=runtime)
            self.assertEqual(result['report'], 'Код: runtime-mismatch')
            self.assertEqual(result['loaded'], [])
        result = self.run_diagnostic(default_manifest=True)
        self.assertEqual(result['report'], 'Код: manifest-changed')
        self.assertEqual(result['loaded'], [])

    def test_missing_changed_and_resized_known_code_are_distinguished(self):
        filename = self.bundle / 'app/mac-main.cjs'
        original = filename.read_bytes()
        filename.unlink()
        result = self.run_diagnostic()
        self.assertIn('Код: code-file-missing', result['report'])
        self.assertIn('Файл программы: app/mac-main.cjs', result['report'])
        self.assertIn('Системный код: ENOENT', result['report'])
        self.assertEqual(result['loaded'], [])
        filename.write_bytes(original.replace(b'CODE', b'FAIL'))
        self.assertIn('Код: code-file-changed', self.run_diagnostic()['report'])
        filename.write_bytes(original + b'changed')
        self.assertIn('Код: code-file-size', self.run_diagnostic()['report'])

    def test_unexpected_metadata_and_unknown_names_never_print_names_or_contents(self):
        for name, stage in (('.DS_Store','ds-store'),('._mac-main.cjs','apple-double'),
                            ('PRIVATE_OWNER_SENTINEL.txt','other')):
            filename = self.bundle / 'app' / name
            filename.write_text('PRIVATE_OWNER_SENTINEL')
            result = self.run_diagnostic()
            self.assertEqual(result['report'], 'Код: unexpected-name-' + stage)
            self.assertEqual(result['loaded'], [])
            filename.unlink()

    def test_root_and_known_file_links_fail_without_loading(self):
        link = self.directory / 'alias'
        link.symlink_to(self.bundle, target_is_directory=True)
        result = self.run_diagnostic(bundle=link)
        self.assertEqual(result['report'], 'Код: root-path')
        self.assertEqual(result['loaded'], [])
        filename = self.bundle / 'app/mac-main.cjs'
        original = filename.read_bytes()
        filename.unlink()
        target = self.directory / 'PRIVATE_OWNER_SENTINEL.cjs'
        target.write_bytes(original)
        filename.symlink_to(target)
        result = self.run_diagnostic()
        self.assertEqual(result['report'], 'Код: code-link\nФайл программы: app/mac-main.cjs')
        self.assertEqual(result['loaded'], [])

    def test_native_error_code_and_cause_are_fixed_and_messages_redacted(self):
        for message, cause in (
            ('/Users/PRIVATE_OWNER_SENTINEL/a.node: code signature invalid', 'native-policy'),
            ('/Users/PRIVATE_OWNER_SENTINEL/a.node: incompatible architecture', 'native-architecture'),
            ('Library not loaded: /Users/PRIVATE_OWNER_SENTINEL/a.dylib', 'native-linker'),
            ('PRIVATE_OWNER_SENTINEL: unclassified native loader error', 'native-other')):
            result = self.run_diagnostic(module_error={'file':'classic-level','code':'ERR_DLOPEN_FAILED','message':message})
            self.assertFalse(result['passed'])
            self.assertEqual(result['report'], 'Код: classic-level-module-load\nСистемный код: ERR_DLOPEN_FAILED\nПричина загрузки: ' + cause)
            self.assertEqual(len(result['loaded']), 1)
        result = self.run_diagnostic(module_error={'file':'koffi','code':'PRIVATE_OWNER_SENTINEL','message':'PRIVATE_OWNER_SENTINEL'})
        self.assertEqual(result['report'], 'Код: koffi-module-load\nСистемный код: unknown-error')

    def test_original_zip_manifest_and_runtime_pins_match_diagnostic(self):
        with zipfile.ZipFile(ROOT / 'preview/mac-private-backup-helper-v95.zip') as archive:
            digest = hashlib.sha256(archive.read('MANIFEST.json')).hexdigest()
            source = DIAGNOSTIC.read_text()
            self.assertIn("OLD_MANIFEST_SHA256 = '" + digest + "'", source)
            launcher = LAUNCHER.read_text()
            for arch in ('arm64','x64'):
                self.assertIn(hashlib.sha256(archive.read('runtime/' + arch + '/node')).hexdigest(), launcher)

    def test_launcher_pins_code_cleans_environment_and_has_no_mutating_commands(self):
        launcher = LAUNCHER.read_text()
        self.assertIn(hashlib.sha256(DIAGNOSTIC.read_bytes()).hexdigest(), launcher)
        self.assertIn('/usr/bin/env -i', launcher)
        self.assertIn('/usr/bin/shasum -a 256', launcher)
        self.assertIn('IFS= read -r task_bundle', launcher)
        for forbidden in ('eval ', 'xattr', 'spctl', 'sudo', 'allow pasting', 'curl ', 'wget ', 'chmod ', 'rm ', 'npm install'):
            self.assertNotIn(forbidden, launcher.lower())
        result = subprocess.run(['bash','-n',str(LAUNCHER)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
