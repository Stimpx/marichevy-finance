"""Fictional demo publication boundary; never uses actual transactions."""
import importlib.util
from decimal import Decimal
from html import unescape
import json
from pathlib import Path
import re
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
        personal_text, catalogue = bundle.detach_merchant_catalog(self.demo)
        self.assertTrue(catalogue)
        values=re.findall(r"(?:url|key|household):'([^']*)'",bundle.CONFIG_RE.search(self.source)[0])
        for value in values:
            self.assertNotIn(value,self.demo)
        for marker in ['gmail.com','supabase.co','9946-WZ3/00067','666991984','247264029','1985-11-27','1988-12-04','2018-01-13','2026-05-17','2023-10-07','МАРИЧЕВ','Маричев','Сергей','Виктория']:
            self.assertNotIn(marker,personal_text)
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

    def test_neutral_brand_names_and_images_survive_redaction_exactly(self):
        _, source_catalogue = bundle.detach_merchant_catalog(self.source)
        _, demo_catalogue = bundle.detach_merchant_catalog(self.demo)
        self.assertEqual(demo_catalogue, source_catalogue)
        self.assertIn('Виктория супермаркет', demo_catalogue)
        self.assertNotIn('Елена супермаркет', self.demo)
        with self.assertRaises(ValueError):
            bundle.transform_demo(self.source.replace('Виктория супермаркет', 'Личное имя в каталоге', 1))

    def test_loan_contract_values_describe_the_fictional_schedule(self):
        info = json.loads(re.search(
            r'const BANK_LOAN_INFO=Object\.freeze\((\{.*?\})\);', self.demo, re.S)[1])
        schedule = json.loads(re.search(
            r'const BANK_LOAN_SCHEDULE=(\[.*?\]);', self.demo, re.S)[1])
        start = self.demo.index('<div class="card loan-contract-info">')
        end = self.demo.index('<section class="section" id="goals">', start)
        contract = self.demo[start:end]
        fields = dict((unescape(label), unescape(re.sub(r'<[^>]*>', '', value)))
            for label, value in re.findall(
                r'<div><span>([^<]+)</span><b>(.*?)</b></div>', contract, re.S))
        self.assertEqual(len(fields), 13, 'keep the contract summary useful in the demo')
        for label, key in {
            'ПСК': 'psk', 'Полная стоимость': 'fullCost',
            'Всего процентов по графику': 'totalInterest',
            'Платёж по графику': 'scheduledPayment', 'Средний платёж': 'averagePayment',
            'Имущественное страхование': 'propertyInsurance',
            'Личное страхование': 'personalInsurance', 'Оценка': 'appraisal',
        }.items():
            with self.subTest(field=label):
                number = re.sub(r'[^\d,.-]', '', fields[label]).replace(',', '.')
                self.assertEqual(Decimal(number), Decimal(str(info[key])),
                    'visible demo value must agree with the calculation input')
        self.assertEqual(int(re.search(r'\d+', fields['Срок'])[0]), len(schedule))
        day, month, year = info['contractDate'].split('.')
        normalized_date = fields['Дата'].replace('декабря', month)
        self.assertEqual([int(part) for part in re.findall(r'\d+', normalized_date)],
            [int(day), int(month), int(year)])
        self.assertNotRegex(contract, r'—\s*(?:₽|%|год\w*|месяц\w*|сентябр\w*)',
            'unknown data must be a whole value, not a dash joined to leftover units')

    def test_demo_loan_redaction_preserves_controls_and_complete_copy(self):
        start = self.demo.index('<div class="card credit-hero-card">')
        end = self.demo.index('<section class="section" id="goals">', start)
        loans = self.demo[start:end]
        self.assertRegex(loans, r'<button[^>]*data-loan-range="1"[^>]*>1 год</button>')
        self.assertRegex(loans, r'<button[^>]*data-loan-range="3"[^>]*>3 года</button>')
        self.assertRegex(loans, r'id="earlyPlanTotal">0\s*₽</b>')
        self.assertRegex(loans, r'id="earlyPlanCount">0 платежей</span>')
        self.assertRegex(loans, r'id="loanActualTotal">0\s*₽</b>')
        plain = unescape(re.sub(r'<[^>]*>', ' ', loans))
        self.assertNotRegex(plain, r'—\s*(?:₽|%|год\w*|месяц\w*|платеж\w*|сентябр\w*)')
        self.assertNotIn('фактические строки банковского Excel-графика', plain)
        self.assertIn('учебн', plain.lower(), 'fictional loan must be labelled as an example')

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
