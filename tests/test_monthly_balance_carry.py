"""Read-only monthly carry from fictional ledger entries, with no external requests."""
from pathlib import Path
import unittest

import test_local_data_safety as harness


class MonthlyBalanceCarry(unittest.TestCase):
    @classmethod
    def setUpClass(cls): harness.LocalDataSafety.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls): harness.LocalDataSafety.tearDownClass.__func__(cls)
    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        self.page.evaluate("""() => {
          session=null;stopCloudSync();localStorage.clear();state=blankState();
          today=()=> '2026-11-01';month=()=> '2026-11';
          loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',payment:1,interest:0,body:1,balance:0}];
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          window.carryRow=(id,date,amount,type='expense',extra={})=>({id,date,amount,type,
            category:type==='income'?'Зарплата':'Продукты',beneficiary:'Общее',who:'Fictional',
            store:'Fictional store',unknown:{keep:[true,null,id]},...extra});
          state.entries=[carryRow('sep-income','2026-09-03',1000,'income'),
            carryRow('sep-expense','2026-09-15',200),carryRow('oct-income','2026-10-03',500,'income'),
            carryRow('oct-expense','2026-10-15',100),carryRow('nov-expense','2026-11-01',25),
            carryRow('future-income','2026-12-03',99999,'income')];
          state.intelligence.accounts=[{id:'manual',name:'Fictional manual account',amount:7654321,updated_at:'2026-01-01T00:00:00Z'}];
          showApp();renderAll();go('home');homeMonth.value='2026-11';renderHome();
        }""")
        self.before = self.snapshot()

    def value(self, selector):
        return self.page.locator(selector).inner_text().replace('\xa0', ' ')

    def test_prior_months_carry_into_new_month_without_changing_monthly_income_or_expense(self):
        self.prepare()
        values=self.page.evaluate("v111MonthBalance('2026-11')")
        self.assertEqual({k:values[k] for k in ['opening','income','expense','result','closing']},
                         {'opening':1200,'income':0,'expense':25,'result':-25,'closing':1175})
        for selector in ['#v111HomeClosing','#heroBalance','#kBalance','#spendableBalance']:
            self.assertIn('1 175',self.value(selector))
        self.assertIn('1 200',self.value('#v111HomeOpening'))
        self.assertIn('0,00',self.value('#v111HomeIncome'))
        self.assertIn('25,00',self.value('#v99HomeExpenseTotal'))
        self.assertIn('25',self.value('#kExpense'))
        self.assertIn('0',self.value('#kIncome'))
        self.assertIn('С прошлого месяца',self.value('#moneyFlow'))
        self.assertIn('Осталось с переносом',self.value('#moneyFlow'))
        self.page.evaluate("go('analytics');analyticsMonth.value='2026-11';renderAnalytics()")
        self.assertEqual(self.page.evaluate("sum(expenses('2026-11'))"),25)
        self.assertIn('25',self.value('#peopleDonutTotal'))
        self.assertEqual(self.snapshot(),self.before)

    def test_empty_month_and_year_boundary_keep_the_previous_closing_and_old_month_is_independent(self):
        self.prepare()
        self.page.evaluate("""() => {state.entries=[
          carryRow('dec-in','2025-12-31',100.30,'income'),carryRow('dec-out','2025-12-31',10.10),
          carryRow('jan-in','2026-01-01',20.40,'income'),carryRow('jan-out','2026-01-31',5.10),
          carryRow('later','2026-03-01',9000,'income')];renderAll();homeMonth.value='2026-02';renderHome()}""")
        before=self.snapshot()
        rows=self.page.evaluate("['2025-11','2025-12','2026-01','2026-02'].map(v111MonthBalance)")
        self.assertEqual([r['closing'] for r in rows],[0,90.20,105.50,105.50])
        self.assertEqual(rows[3]['opening'],rows[2]['closing'])
        self.assertEqual(rows[3]['income'],0)
        self.assertEqual(rows[3]['expense'],0)
        self.assertIn('105,50',self.value('#v111HomeClosing'))
        self.page.locator('#homeMonth').select_option('2025-12')
        self.assertIn('90,20',self.value('#v111HomeClosing'))
        self.assertIn('0,00',self.value('#v111HomeOpening'))
        self.assertEqual(self.snapshot(),before)

    def test_leap_day_and_exact_kopecks_and_legacy_subcents_are_preserved(self):
        self.prepare()
        self.page.evaluate("""() => {state.entries=[
          carryRow('in','2024-02-29',0.30,'income'),carryRow('out-a','2024-02-29',0.10),
          carryRow('out-b','2024-02-29',0.20),carryRow('subcent-in','2024-03-01',0.001,'income'),
          carryRow('subcent-out','2024-03-01',0.0002)]}""")
        before=self.snapshot()
        self.assertEqual(self.page.evaluate("v111MonthBalance('2024-03').opening"),0)
        self.assertAlmostEqual(self.page.evaluate("v111MonthBalance('2024-04').opening"),0.0008,places=12)
        self.assertEqual(self.page.evaluate("v111MonthBalance('2024-02').closing"),0)
        self.assertEqual(self.snapshot(),before)

    def test_negative_carry_stays_negative_while_daily_allowance_is_zero(self):
        self.prepare()
        self.page.evaluate("""() => {state.entries=[carryRow('past','2026-10-31',200)];
          renderAll();homeMonth.value='2026-11';renderHome()}""")
        before=self.snapshot()
        self.assertEqual(self.page.evaluate("v111MonthBalance('2026-11').closing"),-200)
        self.assertIn('−200',self.value('#v111HomeClosing').replace('-', '−'))
        self.assertIn('−200',self.value('#v111HomeOpening').replace('-', '−'))
        self.assertIn('0',self.value('#spendableToday'))
        self.assertEqual(self.snapshot(),before)

    def test_previous_month_comparison_uses_closing_balance_and_future_month_is_excluded(self):
        self.prepare()
        self.page.evaluate("""() => {state.entries=[carryRow('sep','2026-09-01',500,'income'),
          carryRow('oct','2026-10-01',200),carryRow('nov','2026-11-01',100),
          carryRow('future','2026-12-01',9999,'income')];renderAll();homeMonth.value='2026-11';renderHome()}""")
        before=self.snapshot()
        self.assertEqual(self.page.evaluate("v111MonthBalance('2026-10').closing"),300)
        self.assertEqual(self.page.evaluate("v111MonthBalance('2026-11').closing"),200)
        balance=self.page.locator('#monthCompare .compare-item').filter(has_text='Остаток')
        self.assertIn('33.3%',balance.inner_text())
        self.assertEqual(self.snapshot(),before)

    def test_transfers_cash_manual_accounts_and_plans_never_become_income_or_extra_expenses(self):
        self.prepare()
        self.page.evaluate("""() => {state.entries=[carryRow('income','2026-10-01',1000,'income'),
          carryRow('linked','2026-10-02',100,'expense',{category:'Кредит',installmentId:'loan'}),
          carryRow('repayment','2026-10-03',5000,'transfer',{debtRepayment:true,installmentId:'purchase-loan'}),
          carryRow('cash','2026-10-04',9000,'cash'),carryRow('transfer','2026-11-01',8000,'transfer')];
          state.installments=[{id:'loan',kind:'split',parts:[{id:'p',date:'2026-10-02',amount:100}],links:{p:'linked'}},
            {id:'plan-only',kind:'split',parts:[{id:'future',date:'2026-10-03',amount:7000}],links:{}}];
          renderAll();homeMonth.value='2026-11';renderHome()}""")
        before=self.snapshot()
        data=self.page.evaluate("v111MonthBalance('2026-11')")
        self.assertEqual(data['opening'],900)
        self.assertEqual(data['closing'],900)
        self.assertEqual(data['income'],0)
        self.assertEqual(data['expense'],0)
        self.assertEqual(self.snapshot(),before)

    def test_invalid_prior_dates_do_not_enter_carry_and_rows_are_retained_with_warning(self):
        self.prepare()
        self.page.evaluate("""() => {state.entries=[carryRow('valid','2026-02-28',100,'income'),
          carryRow('invalid-day','2026-02-31',9999,'income'),carryRow('invalid-month','2026-00-01',8888,'income'),
          carryRow('invalid-text','not-a-date',7777,'income')];homeMonth.value='2026-11';renderHome()}""")
        before=self.snapshot()
        data=self.page.evaluate("v111MonthBalance('2026-11')")
        self.assertEqual(data['opening'],100)
        self.assertEqual(data['invalidDateCount'],3)
        self.assertTrue(self.page.locator('#v111BalanceWarning').is_visible())
        self.assertIn('3',self.value('#v111BalanceWarning'))
        self.assertIsNone(self.page.evaluate("v111MonthBalance('2026-99')"))
        self.assertIsNone(self.page.evaluate("v111MonthBalance('2026-11-01')"))
        self.assertEqual(self.snapshot(),before)

    def test_balance_breakdown_fits_phone_desktop_and_enlarged_text(self):
        self.prepare()
        for width,scale in [(320,1),(390,1),(1440,1),(390,2),(1440,2)]:
            with self.subTest(width=width,scale=scale):
                self.page.set_viewport_size({'width':width,'height':1000})
                self.page.evaluate('(scale)=>document.documentElement.style.zoom=String(scale)',scale)
                self.page.locator('#v111HomeClosing').scroll_into_view_if_needed()
                result=self.page.locator('.v99-spending-head').evaluate("""root=>({width:innerWidth,
                  doc:document.documentElement.scrollWidth,bad:[root,...root.querySelectorAll('strong,span,button')]
                  .map(node=>{const r=node.getBoundingClientRect();return {id:node.id,left:r.left,right:r.right,sw:node.scrollWidth,cw:node.clientWidth}})
                  .filter(r=>r.left<-.5||r.right>innerWidth+.5||r.sw>r.cw+2)})""")
                self.assertLessEqual(result['doc'],width+1,result)
                self.assertEqual(result['bad'],[],result)
                if scale==1 and width in [390,1440]:
                    directory=Path('/workspace/expense-destinations-review-20261101');directory.mkdir(exist_ok=True)
                    self.page.locator('.v99-spending-head').screenshot(path=str(directory/f'carry-{width}.png'))
        self.assertEqual(self.snapshot(),self.before)


if __name__=='__main__': unittest.main()
