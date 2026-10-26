"""Code-only portable bundle checks; these do not claim native Windows execution."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('offline_builder',ROOT/'tools/build_offline_queue_bundle.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class OfflineBundle(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='fictional-helper-bundle-')
        self.root=Path(self.temp.name)
        self.source=self.root/'source';self.source.mkdir()
        for name in builder.APP+builder.ROOT_FILES:
            shutil.copyfile(builder.SOURCE/name,self.source/name)
        self.dependencies={
            'classic-level/prebuilds/win32-x64/classic-level.node':self.pe(),
            '@koromix/koffi-win32-x64/win32_x64/koffi.node':self.pe(),
        }
        self.inventory={'format':'marichevy-windows-dependencies-v1','files':{k:{'bytes':len(v),'sha256':builder.sha(v)} for k,v in self.dependencies.items()}}
        (self.source/'dependencies.inventory.json').write_text(json.dumps(self.inventory))
        self.exe=self.root/'node.exe';self.exe.write_bytes(self.pe())
        self.license=self.root/'NODE-LICENSE.txt';self.license.write_text('Node.js fictional test license\n'+'x'*11000)
        (self.source/'runtime-pin.json').write_text(json.dumps({'version':'v22.23.4','node_exe_bytes':len(self.pe()),'node_exe_sha256':builder.sha(self.pe()),'node_license_sha256':builder.sha(self.license.read_bytes())}))
        self.output=self.root/'helper.zip'

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def pe():
        data=bytearray(128);data[:2]=b'MZ';struct.pack_into('<I',data,60,80);data[80:84]=b'PE\0\0';struct.pack_into('<H',data,84,0x8664)
        return bytes(data)

    def build(self):
        with patch.object(builder,'SOURCE',self.source),patch.object(builder,'dependency_files',return_value=self.dependencies):
            return builder.build(deps_root=self.root/'unused',node_exe=self.exe,node_license=self.license,output=self.output)

    def extract(self):
        self.build();folder=self.root/'extracted';folder.mkdir()
        with zipfile.ZipFile(self.output) as archive:
            archive.extractall(folder)
        return folder

    def verify(self,folder):
        node=shutil.which('node')
        if not node:self.skipTest('Node required for bootstrap verification')
        code="const {verifyBundle}=require(process.argv[1]);verifyBundle(process.argv[2]).then(()=>process.exitCode=0).catch(()=>process.exitCode=7)"
        result=subprocess.run([node,'-e',code,str(ROOT/'tools/offline_queue/bootstrap.cjs'),str(folder)],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.stdout,'');self.assertEqual(result.stderr,'')
        return result.returncode

    def test_exact_manifest_and_private_output_directory_excluded(self):
        folder=self.extract()
        private=folder/'PRIVATE-backup-old';private.mkdir()
        (private/'fictional-secret.json').write_text('OWNER_ONLY_SENTINEL')
        # A deliberately unreadable output directory is not traversed or hashed.
        private.chmod(0)
        try:self.assertEqual(self.verify(folder),0)
        finally:private.chmod(0o700)
        with zipfile.ZipFile(self.output) as archive:
            names=archive.namelist()
            self.assertNotIn('OWNER_ONLY_SENTINEL',b''.join(archive.read(n) for n in names).decode('utf8',errors='ignore'))
            self.assertTrue(all(not n.startswith('PRIVATE') for n in names))
            self.assertIn('app/selftest.cjs',names)

    def test_changed_helper_and_shadow_module_fail_before_load(self):
        folder=self.extract()
        main=folder/'app/main.cjs';original=main.read_bytes();main.write_bytes(original+b'\n// changed')
        self.assertEqual(self.verify(folder),7)
        main.write_bytes(original)
        extra=folder/'app/node_modules/foreign-injection.cjs';extra.write_text('throw new Error("must not execute")')
        self.assertEqual(self.verify(folder),7)

    def test_traversal_private_manifest_reference_and_symlink_rejected(self):
        folder=self.extract();manifest=folder/'MANIFEST.json';original=manifest.read_text();value=json.loads(original)
        for name in ('../outside','PRIVATE-backup-old/secret.json','app/../README_RU.txt','C:/secret',
                     'app/.. /.. /PRIVATE-backup-old/secret.json','app/../. /outside',
                     'app/main.cjs.','app/space /module.js','app/CON.js','app/NUL','app/LPT1.txt',
                     'app/has\x00nul','app/wild*card','app/question?mark','app/quote"name','app/pipe|name'):
            variant=json.loads(original);variant['files'][0]['path']=name;manifest.write_text(json.dumps(variant))
            self.assertEqual(self.verify(folder),7)
        manifest.write_text(original)
        main=folder/'app/main.cjs';target=self.root/'outside-main.cjs';target.write_bytes(main.read_bytes());main.unlink();main.symlink_to(target)
        self.assertEqual(self.verify(folder),7)

    def test_runtime_and_dependency_mismatch_fail_without_artifact(self):
        self.exe.write_bytes(self.pe()+b'changed')
        with self.assertRaisesRegex(ValueError,'runtime mismatch'):self.build()
        self.assertFalse(self.output.exists())
        self.exe.write_bytes(self.pe());self.dependencies['extra.js']=b'changed'
        with self.assertRaisesRegex(ValueError,'dependency bytes'):self.build()
        self.assertFalse(self.output.exists())

    def test_existing_archive_is_preserved(self):
        self.output.write_bytes(b'OLD_ARCHIVE_MUST_STAY')
        with self.assertRaisesRegex(ValueError,'new ZIP'):self.build()
        self.assertEqual(self.output.read_bytes(),b'OLD_ARCHIVE_MUST_STAY')

    def test_launcher_is_local_and_clears_node_preload_configuration(self):
        launcher=(builder.SOURCE/'Start backup.cmd').read_text()
        self.assertIn('set "NODE_OPTIONS="',launcher)
        self.assertIn('set "NODE_PATH="',launcher)
        self.assertIn('--no-global-search-paths',launcher)
        for blocked in ('powershell','executionpolicy','allow pasting','curl','wget','npm install','runas'):
            self.assertNotIn(blocked,launcher.lower())
        self.assertIn('runtime\\node.exe',launcher)
        # A native startup failure or partial ZIP extraction must remain visible
        # instead of disappearing when the owner presses an arbitrary key.
        self.assertIn('/D /V:OFF /K',launcher)
        self.assertIn('setlocal DisableDelayedExpansion',launcher)
        self.assertIn('""Start backup.cmd" --keep-window"',launcher)
        self.assertNotIn('%~f0',launcher)
        self.assertNotIn('pause',launcher.lower())
        for required in ('app\\bootstrap.cjs','MANIFEST.json','Извлечь всё','СОХРАНЕНО'):
            self.assertIn(required,launcher)


if __name__=='__main__':unittest.main()
