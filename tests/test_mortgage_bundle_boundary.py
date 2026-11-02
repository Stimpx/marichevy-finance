"""Current bank schedules/checkpoints cannot cross demo/public build boundaries.

The default fixture injects fictional bank data into the local UI source. Set
MORTGAGE_BUNDLE_SOURCE to review an actual new UI candidate without publishing
or rewriting the checked-in public template.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from build_bundle import detach_merchant_catalog, transform_demo
from build_public_client import transform_public


def fixture_source():
    path = Path(os.environ.get('MORTGAGE_BUNDLE_SOURCE', ROOT / 'index.html'))
    source = path.read_text()
    if 'const BANK_LOAN_CURRENT_SCHEDULE=' not in source:
        # Distinct fictional amounts model all three new personal-data sources.
        fixture = '''const BANK_LOAN_CURRENT_SCHEDULE=[[1,"02.11.2026",41.23,98.76,139.99,987654.32]];
const BANK_LOAN_CURRENT_CHARGES=[{"payDate":"2030-08-31","payment":13579.24}];
const BANK_LOAN_RECONCILIATION=Object.freeze({version:1,source:'private-bank-unit-fixture',date:'2026-11-02',balance:987654.32,outstandingInterest:1234.56,fullRepaymentAmount:988888.88,endDate:'2040-10-31'});
function v125BankScheduleData(){
 return BANK_LOAN_CURRENT_SCHEDULE;
}
'''
        source = source.replace('const BANK_LOAN_INFO=', fixture+'const BANK_LOAN_INFO=', 1)
    if 'const FAMILY_DOCUMENT_PLANS=' not in source:
        plans = '''const FAMILY_DOCUMENT_PLANS=[{"id":"private-document-unit-fixture","kind":"split","provider":"Fictional document provider","title":"Private document boundary fixture","amount":1234.56,"parts":[{"id":"private-document-part","date":"2027-01-14","amount":1234.56}],"sourceFingerprint":"opaque-test-document-fingerprint"}];
function documentPlanBoundaryFixture(){return FAMILY_DOCUMENT_PLANS}
'''
        source = source.replace('let state=loadLocal();', plans+'let state=loadLocal();', 1)
    return source


class MortgageBundleBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = fixture_source()
        cls.demo = transform_demo(cls.source)
        cls.public = transform_public(cls.source)

    def array(self, html, name):
        return json.loads(re.search(r'const '+name+r'=(\[.*?\]);', html, re.S)[1])

    def test_demo_current_schedule_is_the_coherent_fictional_schedule(self):
        original = self.array(self.demo, 'BANK_LOAN_SCHEDULE')
        current = self.array(self.demo, 'BANK_LOAN_CURRENT_SCHEDULE')
        self.assertEqual(current, original)
        self.assertEqual(len(current), 12)
        self.assertEqual(current[0][1], '15.01.2027')
        self.assertEqual(sum(row[2] for row in current), 120000)
        self.assertEqual(current[-1][-1], 0)

    def test_demo_has_no_real_charges_or_bank_checkpoint(self):
        self.assertEqual(self.array(self.demo, 'BANK_LOAN_CURRENT_CHARGES'), [])
        self.assertIn('const BANK_LOAN_RECONCILIATION=Object.freeze({});', self.demo)
        self.assertIn("bankVersion:'fictional-demo'", self.demo)

    def test_unconfigured_public_family_gets_no_bank_rows_or_checkpoint(self):
        for name in ('BANK_LOAN_SCHEDULE', 'BANK_LOAN_CURRENT_SCHEDULE',
                     'BANK_LOAN_CURRENT_CHARGES'):
            self.assertEqual(self.array(self.public, name), [], name)
        self.assertIn('const BANK_LOAN_RECONCILIATION=Object.freeze({});', self.public)
        self.assertIn("bankVersion:'unconfigured'", self.public)

    def test_checkpoint_and_current_schedule_values_do_not_survive_redaction(self):
        checkpoint = re.search(r'const BANK_LOAN_RECONCILIATION=Object\.freeze\((\{.*?\})\);',
                               self.source, re.S)[1]
        markers = [re.search(r'const BANK_LOAN_CURRENT_SCHEDULE=(\[.*?\]);', self.source, re.S)[1],
                   re.search(r'const BANK_LOAN_CURRENT_CHARGES=(\[.*?\]);', self.source, re.S)[1],
                   checkpoint]
        # Precise bank balances must not remain in another copied code/display
        # field after the three data blocks were replaced.
        markers.extend(re.findall(r'(?:balance|outstandingInterest|fullRepaymentAmount):\s*(\d+\.\d+)',
                                  checkpoint))
        for html in (self.demo, self.public):
            personal_text, _ = detach_merchant_catalog(html)
            for marker in markers:
                self.assertNotIn(marker, personal_text)

    def test_partial_or_renamed_current_bank_source_stops_both_builds(self):
        for name in ('BANK_LOAN_CURRENT_SCHEDULE', 'BANK_LOAN_CURRENT_CHARGES',
                     'BANK_LOAN_RECONCILIATION'):
            changed = self.source.replace('const '+name+'=', 'const RENAMED_PRIVATE_BANK_DATA=', 1)
            for transform in (transform_demo, transform_public):
                with self.subTest(name=name, transform=transform.__name__):
                    with self.assertRaises(ValueError):
                        transform(changed)

    def test_unreviewed_new_bank_data_block_stops_both_builds(self):
        changed = self.source.replace('const BANK_LOAN_INFO=',
            'const BANK_LOAN_PRIVATE_HISTORY=[987654.32];\nconst BANK_LOAN_INFO=', 1)
        for transform in (transform_demo, transform_public):
            with self.assertRaises(ValueError):
                transform(changed)

    def test_missing_bank_reader_stops_both_builds(self):
        changed = self.source.replace('function v125BankScheduleData(){',
                                      'function renamedPrivateBankReader(){', 1)
        for transform in (transform_demo, transform_public):
            with self.assertRaises(ValueError):
                transform(changed)

    def test_personal_document_obligations_cannot_seed_demo_or_public(self):
        source_plans = self.array(self.source, 'FAMILY_DOCUMENT_PLANS')
        self.assertTrue(source_plans, 'fixture must exercise a nonempty personal plan')
        markers = [json.dumps(source_plans, ensure_ascii=False, separators=(',', ':'))]
        for plan in source_plans:
            markers.extend(str(plan[key]) for key in ('id', 'sourceFingerprint') if plan.get(key))
        for html in (self.demo, self.public):
            self.assertEqual(self.array(html, 'FAMILY_DOCUMENT_PLANS'), [])
            for marker in markers:
                self.assertNotIn(marker, html)

    def test_partial_renamed_or_new_document_plan_block_stops_both_builds(self):
        changed_sources = [
            self.source.replace('const FAMILY_DOCUMENT_PLANS=', 'const RENAMED_DOCUMENT_PLANS=', 1),
            self.source.replace('const FAMILY_DOCUMENT_PLANS=',
                                'const FAMILY_DOCUMENT_PRIVATE_HISTORY=[1234.56];\nconst FAMILY_DOCUMENT_PLANS=', 1),
            self.source.replace('const FAMILY_DOCUMENT_PLANS=', 'const FAMILY_DOCUMENT_PLANS =', 1),
        ]
        for changed in changed_sources:
            for transform in (transform_demo, transform_public):
                with self.assertRaises(ValueError):
                    transform(changed)

    def test_transforms_are_pure_and_keep_demo_network_guard(self):
        before = hashlib.sha256(self.source.encode()).hexdigest()
        self.assertEqual(self.demo, transform_demo(self.source))
        self.assertEqual(self.public, transform_public(self.source))
        self.assertEqual(hashlib.sha256(self.source.encode()).hexdigest(), before)
        self.assertIn("connect-src 'none'", self.demo)
        self.assertIn('navigator.sendBeacon=()=>false', self.demo)
        self.assertNotIn('window.fetch=()=>Promise.reject', self.public)

    def test_delivered_inline_javascript_still_parses(self):
        with tempfile.TemporaryDirectory(prefix='mortgage-build-boundary-') as folder:
            for kind, html in (('demo', self.demo), ('public', self.public)):
                for index, script in enumerate(re.findall(r'<script\b[^>]*>(.*?)</script>', html,
                                                          re.S | re.I)):
                    path = Path(folder) / f'{kind}-{index}.js'
                    path.write_text(script)
                    result = subprocess.run(['node', '--check', str(path)],
                                            capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0,
                                     f'{kind} inline script {index}: {result.stderr[:500]}')


if __name__ == '__main__':
    unittest.main()
