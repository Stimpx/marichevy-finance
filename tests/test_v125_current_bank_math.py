"""Revised bank schedule: principal payoff and remaining interest are distinct."""
import argparse
import calendar
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import unittest

import test_v125_mortgage_math as original


class CurrentBankMath(original.MortgageMath):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.bank = json.loads((Path(__file__).parent / 'fixtures' / 'v125_bank_169.json').read_text())
        for i,r in enumerate(cls.bank):
            serial=2026*12+9+i
            year,month0=divmod(serial,12)
            month=month0+1
            r['periodEnd']=f'{year:04d}-{month:02d}-{calendar.monthrange(year,month)[1]:02d}'
            r['bankVersion']='2026-11-02'

    def current(self, code):
        return self.js('const CURRENT_FIXTURE='+json.dumps(self.bank)+';v125BankScheduleData=()=>CURRENT_FIXTURE;'+code)

    def test_revised_169_rows_include_interest_tail_and_first_40000_only_once(self):
        s=self.current("console.log(JSON.stringify(simulateEarlyPlan([],'term')));")
        self.assertEqual(len(s['rows']),169)
        self.assertEqual(s['rows'][0]['total'],201830.21)
        self.assertEqual(s['rows'][0]['body'],41802.81)
        self.assertEqual(s['rows'][0]['balance'],4458197.19)
        self.assertEqual(s['rows'][-1]['interest'],25.22)
        self.assertEqual(s['rows'][-1]['body'],0)
        self.assertEqual(s['principalEndDate'],'2040-10-01')
        self.assertEqual(s['endDate'],'2040-10-31')
        self.assertEqual(s['totalInterest'],10001476.14)
        self.assertEqual(s['totalCash'],14661870.12)
        self.assertTrue(s['paidOff'])
        for actual,expected in zip(s['rows'],self.bank):
            for a,b in [('date','payDate'),('total','payment'),('body','body'),('interest','interest'),('balance','balance')]:
                self.assertEqual(actual[a],expected[b])

    def test_bank_anchor_keeps_all_168_future_rows_exactly(self):
        s=self.current("const base=CURRENT_FIXTURE.filter(r=>r.payDate>'2026-11-02');console.log(JSON.stringify(simulateEarlyPlan([],'term',{base,openingBalance:4458197.19,openingDate:'2026-11-02'})));")
        self.assertEqual(len(s['rows']),168)
        self.assertEqual(s['rows'][0]['interest'],80664.37)
        self.assertEqual(s['rows'][-1]['total'],25.22)
        self.assertEqual(s['principalEndDate'],'2040-10-01')
        self.assertEqual(s['endDate'],'2040-10-31')
        self.assertEqual(s['totalInterest'],9841448.74)

    def test_daily_extra_after_anchor_preserves_unpaid_november_interest(self):
        s=self.current("const base=CURRENT_FIXTURE.filter(r=>r.payDate>'2026-11-02');console.log(JSON.stringify(simulateEarlyPlan([{date:'2026-11-03',amount:10000}],'term',{base,openingBalance:4458197.19,openingDate:'2026-11-02'})));")
        self.assertTrue(s['dailyInterest'])
        self.assertFalse(s['interestSeedEstimated'])
        self.assertEqual(s['rows'][0]['total'],10000)
        self.assertEqual(s['rows'][0]['interest'],0)
        self.assertEqual(s['rows'][1]['date'],'2026-11-30')
        self.assertEqual(s['rows'][1]['interest'],80501.63)
        self.assertEqual(s['totalExtra'],10000)

    def test_full_closure_after_anchor_also_pays_5424_interest_already_accrued(self):
        s=self.current("const base=CURRENT_FIXTURE.filter(r=>r.payDate>'2026-11-02');console.log(JSON.stringify(simulateEarlyPlan([{date:'2026-11-03',amount:5000000}],'term',{base,openingBalance:4458197.19,openingDate:'2026-11-02'})));")
        self.assertTrue(s['paidOff'])
        self.assertEqual(s['endDate'],'2026-11-03')
        self.assertEqual(s['principalEndDate'],'2026-11-03')
        self.assertEqual(s['rows'][0]['interest'],8111.79)
        self.assertEqual(s['rows'][0]['body'],4458197.19)
        self.assertEqual(s['totalUnused'],541802.81)

    def test_same_day_one_ruble_is_additional_to_already_amended_bank_row(self):
        s=self.current("console.log(JSON.stringify(simulateEarlyPlan([{date:'2026-11-02',amount:1}],'term')));")
        self.assertEqual(s['rows'][0]['body'],41802.81)
        self.assertEqual(s['rows'][0]['total'],201830.21)
        self.assertEqual(s['rows'][1]['body'],1)
        self.assertEqual(s['rows'][1]['balance'],4458196.19)
        self.assertEqual(s['rows'][2]['interest'],80664.35)
        self.assertEqual(s['monthsSaved'],0)

    def test_principal_already_zero_still_pays_known_interest_tail(self):
        s=self.current("console.log(JSON.stringify(simulateEarlyPlan([{date:'2040-10-31',amount:1}],'term')));")
        self.assertTrue(s['paidOff'])
        self.assertEqual(s['principalEndDate'],'2040-10-01')
        self.assertEqual(s['endDate'],'2040-10-31')
        self.assertEqual(s['rows'][0]['interest'],25.22)
        self.assertEqual(s['totalExtra'],0)
        self.assertEqual(s['totalUnused'],1)

    def test_calendar_daily_opening_balance_rule_reproduces_every_bank_interest_row(self):
        D=Decimal
        changes={date.fromisoformat(r['payDate']):D(str(r['body'])) for r in self.bank}
        balance=D('4500000');cursor=date(2026,9,3);accrued=D(0);paid=D(0)
        for row in self.bank:
            period_end=date.fromisoformat(row['periodEnd'])
            while cursor<=period_end:
                accrued+=balance*D('.22')/D(366 if calendar.isleap(cursor.year) else 365)
                balance-=changes.get(cursor,D(0))
                cursor+=timedelta(days=1)
            due=accrued.quantize(D('.01'),rounding=ROUND_HALF_UP)-paid
            self.assertEqual(due,D(str(row['interest'])),row['payDate'])
            paid+=due


# Keep this suite separate from the ten original-contract regressions.
for name in list(original.MortgageMath.__dict__):
    if name.startswith('test_'):
        setattr(CurrentBankMath,name,None)

if __name__=='__main__':
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--html',type=Path)
    args,rest=p.parse_known_args()
    if args.html:original.HTML=args.html.resolve()
    unittest.main(argv=[__file__,*rest])
