"""Direct regressions for real simulator JS; no cloud, storage or personal data reads."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import unittest

HTML = Path(os.environ.get('MARICHEVY_HTML', str(Path(__file__).resolve().parents[1] / 'index.html')))


class MortgageMath(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        html = HTML.read_text()
        start = html.index('const BANK_LOAN_SCHEDULE=')
        end = html.index('function money2', start)
        sim_start = html.index('function simulateEarlyPlan(')
        sim_end = html.index('\n}\n', sim_start) + 3
        cls.source = html[start:end] + '\n' + html[sim_start:sim_end]
        if 'function loanScheduleData(' not in cls.source:
            cls.source += '\nfunction loanScheduleData(){return BANK_LOAN_SCHEDULE.map(r=>({n:r[0],payDate:r[1].split(\".\").reverse().join(\"-\"),periodEnd:r[1].split(\".\").reverse().join(\"-\"),payment:r[4],interest:r[3],body:r[2],balance:r[5]}))}'

        # Pin the original contract fixture for the historical 40-month bug.
        # The revised-bank suite installs its own independent current fixture.
        cls.source += '\nfunction v125BankScheduleData(){return loanScheduleData()}'

    def js(self, code):
        result = subprocess.run(['node', '-'], input=self.source + '\n' + code,
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)

    def test_no_extra_preserves_exact_bank_rows_including_charges(self):
        data = self.js("const b=loanScheduleData(),s=simulateEarlyPlan([],'term');console.log(JSON.stringify({b,s}));")
        sim, bank = data['s'], data['b']
        self.assertTrue(sim['paidOff'])
        self.assertEqual(sim['monthsSaved'], 0)
        self.assertEqual(sim['endDate'], bank[-1]['payDate'])
        self.assertEqual(len(sim['rows']), len(bank))
        for actual, expected in zip(sim['rows'], bank):
            for a,b in [('date','payDate'),('total','payment'),('body','body'),('interest','interest'),('balance','balance')]:
                self.assertEqual(actual[a], expected[b])
        self.assertEqual(sim['totalCash'], 15533128.88)

    def test_40000_on_first_due_matches_bank_end_date_and_actual_cash(self):
        s = self.js("console.log(JSON.stringify(simulateEarlyPlan([{date:'2026-11-02',amount:40000}],'term')));")
        self.assertTrue(s['paidOff'])
        self.assertEqual(s['endDate'], '2040-10-01')
        self.assertEqual(s['monthsSaved'], 11)
        regular, extra = s['rows'][:2]
        self.assertEqual(regular['kind'], 'scheduled')
        self.assertEqual(regular['interest'], 160027.4)
        self.assertEqual(regular['body'], 1802.81)
        self.assertEqual(extra['kind'], 'extra')
        self.assertEqual(extra['total'], 40000)
        self.assertEqual(extra['balance'], 4458197.19)
        self.assertEqual(round(regular['total'] + extra['total'], 2), 201830.21)

    def test_one_ruble_cannot_magic_years_off_term(self):
        s = self.js("console.log(JSON.stringify(simulateEarlyPlan([{date:'2026-11-02',amount:1}],'term')));")
        self.assertEqual(s['monthsSaved'], 0)
        self.assertEqual(s['endDate'], '2041-09-02')
        self.assertEqual(s['rows'][1]['total'], 1)
        self.assertEqual(s['rows'][1]['balance'], 4498196.19)

    def test_partial_between_due_dates_does_not_charge_interest_twice(self):
        data = self.js("const s=simulateEarlyPlan([{date:'2026-10-21',amount:50000}],'term');console.log(JSON.stringify(s));")
        ex, scheduled = data['rows'][:2]
        self.assertEqual(ex['kind'], 'extra')
        self.assertEqual(ex['interest'], 0)
        self.assertEqual(ex['total'], 50000)
        self.assertGreater(scheduled['interest'], 0)
        self.assertLess(scheduled['interest'], 160027.4)
        self.assertEqual(scheduled['total'], 161830.21)
        self.assertEqual(round(ex['total'] + scheduled['total'], 2), 211830.21)

    def test_full_midperiod_closure_pays_accrued_interest_once_and_excess_unused(self):
        s = self.js("console.log(JSON.stringify(simulateEarlyPlan([{date:'2026-10-21',amount:5000000},{date:'2026-11-15',amount:10000}],'term')));")
        self.assertTrue(s['paidOff'])
        self.assertEqual(s['endDate'], '2026-10-21')
        self.assertEqual(s['totalExtra'], 4500000)
        self.assertEqual(s['totalUnused'], 510000)
        self.assertGreater(s['totalInterest'], 0)
        self.assertEqual(s['totalInterest'], s['rows'][0]['interest'])
        self.assertEqual(s['rows'][0]['total'], round(4500000+s['totalInterest'], 2))
        self.assertTrue(all(r['kind']=='unused' for r in s['rows'][1:]))

    def test_repeated_variable_extras_conserve_cash_and_principal(self):
        data = self.js("console.log(JSON.stringify(['term','payment'].map(mode=>simulateEarlyPlan([{date:'2026-10-21',amount:10000.25},{date:'2026-11-02',amount:40000.01},{date:'2026-11-02',amount:250.99},{date:'2027-01-05',amount:15000.5}],mode))));")
        for s in data:
            balance = 4500000
            for r in s['rows']:
                self.assertGreaterEqual(r['body'], 0)
                self.assertLessEqual(r['body'], balance+.005)
                self.assertAlmostEqual(r['balance'], balance-r['body'], places=2)
                self.assertAlmostEqual(r['total'], r['body']+r['interest']+r['charges'], places=2)
                balance = r['balance']
            self.assertEqual(round(sum(r['total'] for r in s['rows']),2), s['totalCash'])
            self.assertEqual(round(sum(r['interest'] for r in s['rows']),2), s['totalInterest'])
            self.assertEqual(s['totalExtra']+s['totalUnused'], round(10000.25+40000.01+250.99+15000.5,2))

    def test_opening_anchor_uses_supplied_debt_and_future_rows(self):
        s = self.js("const future=loanScheduleData().filter(r=>r.payDate>'2026-11-02');console.log(JSON.stringify(simulateEarlyPlan([],'term',{base:future,openingBalance:4458197.19,openingDate:'2026-11-02'})));")
        self.assertEqual(s['rows'][0]['date'], '2026-11-30')
        self.assertEqual(s['rows'][0]['interest'], 80616.12)
        self.assertEqual(s['rows'][0]['balance'], 4452928.31)
        self.assertEqual(s['endDate'], '2040-10-01')
        self.assertAlmostEqual(s['rows'][0]['body']+s['rows'][0]['balance'], 4458197.19, places=2)

    def test_nonzero_residual_never_reports_a_payoff_date(self):
        s = self.js("const b=[{payDate:'2026-12-01',payment:50,interest:10,body:40,balance:960}];console.log(JSON.stringify(simulateEarlyPlan([],'term',{base:b,openingBalance:1000,openingDate:'2026-11-01'})));")
        self.assertFalse(s['paidOff'])
        self.assertIsNone(s['endDate'])
        self.assertGreater(s['remainingBalance'], 0)
        self.assertEqual(s['monthsSaved'], 0)

    def test_bank_source_avoids_projection_recursion(self):
        s = self.js("const bank=loanScheduleData();function v125BankScheduleData(){return bank}loanScheduleData=()=>{throw Error('projected source must not be read')};console.log(JSON.stringify(simulateEarlyPlan([{date:'2026-11-02',amount:40000}],'term')));")
        self.assertEqual(s['endDate'], '2040-10-01')

    def test_invalid_dates_money_and_opening_anchors_rejected(self):
        result = self.js("const e=[{date:'2026-02-31',amount:1},{date:'2027-02-29',amount:1},{date:'2026-11-02',amount:-1},{date:'2026-11-02',amount:'40000'},{date:'2026-11-02',amount:Infinity}];const a=e.map(x=>simulateEarlyPlan([x],'term'));a.push(simulateEarlyPlan([],'term',{openingBalance:-1,openingDate:'2026-11-02'}));a.push(simulateEarlyPlan([],'term',{openingBalance:1,openingDate:'2026-02-31'}));console.log(JSON.stringify(a));")
        self.assertTrue(all(x is None for x in result))


if __name__ == '__main__':
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument('--html', type=Path)
    args, rest = p.parse_known_args()
    if args.html:
        HTML = args.html.resolve()
    unittest.main(argv=[__file__, *rest])
