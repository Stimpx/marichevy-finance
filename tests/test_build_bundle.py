"""Fictional demo publication boundary; never uses actual transactions."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build_bundle as bundle

class DemoBundle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/'index.html').read_text()
        cls.demo=bundle.transform_demo(cls.source)

    def test_personal_configuration_is_removed(self):
        import re
        values=re.findall(r"(?:url|key|household):'([^']*)'",bundle.CONFIG_RE.search(self.source)[0])
        for value in values:
            self.assertNotIn(value,self.demo)
        for marker in ['gmail.com','supabase.co','9946-WZ3/00067','666991984','247264029','1985-11-27','1988-12-04','2018-01-13','2026-05-17','2023-10-07','МАРИЧЕВ','Маричев','Сергей','Виктория']:
            self.assertNotIn(marker,self.demo)
        self.assertIn('София',self.demo)
        self.assertNotIn('английский алисы',self.demo)
        self.assertIn('английский софии',self.demo)
        self.assertNotIn('telegramSergey',self.demo)
        self.assertNotIn('telegramVictoria',self.demo)
        self.assertIn('telegramAlexey',self.demo)
        self.assertIn('telegramElena',self.demo)
        self.assertIn('marichevy_demo_state_v10',self.demo)
        self.assertNotIn('marichevy_state_v10',self.demo)

    def test_offline_policy_precedes_app_code(self):
        self.assertLess(self.demo.index('connect-src'),self.demo.index('const CONFIG'))
        self.assertIn("connect-src 'none'",self.demo)
        self.assertIn('navigator.sendBeacon=()=>false',self.demo)
        self.assertIn('XMLHttpRequest.prototype.open=denied',self.demo)
        self.assertIn("localStorage.getItem('marichevy_demo_state_v10')===null",self.demo)

    def test_changed_source_shape_fails_closed(self):
        with self.assertRaises(ValueError):
            bundle.transform_demo(self.source.replace('const FAMILY_BIRTHS=', 'const RENAMED_BIRTHS='))

    def test_bundle_allowlists_and_determinism(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)
            bundle.build(output)
            first=(output/'safe-demo.zip').read_bytes()
            with zipfile.ZipFile(output/'safe-demo.zip') as archive:
                self.assertEqual(set(archive.namelist()),{'index.html','favicon.svg','_headers','README.txt','OWNER_REVIEW_RU.md','BUILD.json','MANIFEST.json'})
                manifest=json.loads(archive.read('MANIFEST.json'))
                for name,digest in manifest.items():
                    self.assertEqual(bundle.hashlib.sha256(archive.read(name)).hexdigest(),digest)
            with zipfile.ZipFile(output/'personal-installation-PRIVATE.zip') as archive:
                self.assertEqual(archive.read('index.html'),(ROOT/'index.html').read_bytes())
                self.assertIn('CNAME',archive.namelist())
                self.assertIn('server/001_family_state_cas.sql',archive.namelist())
                self.assertEqual(json.loads(archive.read('BUILD.json'))['source_sha256'],bundle.hashlib.sha256((ROOT/'index.html').read_bytes()).hexdigest())
            bundle.build(output)
            self.assertEqual(first,(output/'safe-demo.zip').read_bytes())
            (output/'safe-demo'/'unexpected-private.txt').write_text('fictional stale data')
            with self.assertRaises(ValueError):
                bundle.build(output)

if __name__=='__main__':unittest.main()
