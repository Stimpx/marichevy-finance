"""Recorded-data monthly review; fictional rows, no external traffic or writes."""
import unittest

import test_local_data_safety as harness


class MonthlyReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open
    snapshot = harness.LocalDataSafety.snapshot

    def prepare(self):
        self.open()
        info=self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          const current=month(),chosen=previousMonthKey(current),previous=previousMonthKey(chosen);
          const row=(id,date,type,amount,category='Продукты')=>({id,date,type,amount,category,
            beneficiary:'Общее',who:'Legacy preserved',store:'Fictional '+id,
            futureField:{keep:[true,null,'untouched']}});
          state.entries=[row('old-first',chosen+'-04','expense',0.10),
            row('old-second',chosen+'-05','expense',0.20),row('old-income',chosen+'-01','income',1),
            row('previous',previous+'-03','expense',0.15),
            row('current-expense',current+'-04','expense',9999.99),
            row('current-income',current+'-01','income',20000),
            row('transfer',chosen+'-06','transfer',5000),row('cash',chosen+'-06','cash',7000)];
          showApp();renderAll();document.getElementById('homeMonth').value=chosen;
          document.getElementById('homeMonth').dispatchEvent(new Event('change',{bubbles:true}));go('home');
          return {chosen,current,previous,group:expenseEntryGroup(state.entries[0]),label:v84MonthLabel(chosen)};
        }""")
        self.info=info;self.before=self.snapshot()

    def test_historical_selected_month_uses_recorded_rows_and_exact_cents(self):
        self.prepare()
        self.assertEqual(self.page.locator('#v96MonthlyPeriod').inner_text(),self.info['label'])
        self.assertIn('0,30',self.page.locator('#v96MonthlyExpense').inner_text())
        self.assertIn('1,00',self.page.locator('#v96MonthlyIncome').inner_text())
        self.assertIn('0,70',self.page.locator('#v96MonthlyResult').inner_text())
        data=self.page.evaluate('v96MonthlyReviewData()')
        self.assertEqual((data['spent'],data['income'],data['result']),(0.3,1,0.7))
        self.assertEqual((data['expenseCount'],data['incomeCount']),(2,1))
        self.assertIn('100,0%',self.page.locator('#v96MonthlyComparisonText').inner_text())
        self.assertNotIn('ещё не завершён',self.page.locator('#v96MonthlyComparisonCaution').inner_text())
        self.assertEqual(self.snapshot(),self.before)

    def test_actual_month_selector_rerenders_and_warns_current_month_incomplete(self):
        self.prepare()
        self.page.locator('#homeMonth').select_option(self.info['current'])
        self.assertEqual(self.page.evaluate('v96MonthlyReviewData().month'),self.info['current'])
        self.assertIn('9\u00a0999,99',self.page.locator('#v96MonthlyExpense').inner_text())
        self.assertIn('ещё не завершён',self.page.locator('#v96MonthlyComparisonCaution').inner_text())
        self.assertIn('предварительное',self.page.locator('#v96MonthlyComparisonCaution').inner_text())
        self.assertEqual(self.snapshot(),self.before)

    def test_empty_month_is_helpful_without_fake_percent_or_budget_verdict(self):
        self.prepare()
        self.page.evaluate("state.entries=[];renderAll();go('home')")
        before=self.snapshot();region=self.page.locator('#v96MonthlyReview')
        self.assertTrue(region.is_visible())
        self.assertEqual(region.locator('[data-month-review-card]').count(),3)
        self.assertNotIn('%',region.inner_text())
        self.assertIn('пока не внесены',self.page.locator('#v96MonthlyIncomeNote').inner_text())
        for word in ['дефицит','остановить','сократить','семья в плюсе','можно отложить']:
            self.assertNotIn(word,region.inner_text().lower())
        region.get_by_role('button',name='Добавить доход',exact=True).click()
        self.assertEqual(self.page.locator('#eType').input_value(),'income')
        self.assertEqual(self.snapshot(),before)
        self.page.evaluate("go('home')")
        region.get_by_role('button',name='Добавить расход',exact=True).click()
        self.assertEqual(self.page.locator('#eType').input_value(),'expense')
        self.assertEqual(self.snapshot(),before)

    def test_missing_income_and_medical_spending_do_not_trigger_cut_spending_advice(self):
        self.prepare()
        self.page.evaluate("""() => {
          const m=homeMonth();state.entries=[{id:'medical',type:'expense',date:m+'-02',
            amount:100.10,category:'Аптека и медицина',who:'Legacy preserved',beneficiary:'Общее'}];
          renderAll();go('home');
        }""")
        before=self.snapshot();text=self.page.locator('#v96MonthlyReview').inner_text().lower()
        self.assertIn('доходы за выбранный месяц пока не внесены',text)
        self.assertIn('−100,10',self.page.locator('#v96MonthlyResult').inner_text().replace('-','−'))
        for word in ['сократ','останов','дефицит','можно отложить','семья в плюсе']:
            self.assertNotIn(word,text)
        self.assertIn('Откройте операции',self.page.locator('[data-month-review-card="largest"]').inner_text())
        self.assertEqual(self.snapshot(),before)

    def test_no_previous_and_zero_previous_never_generate_fake_percent(self):
        self.prepare()
        for keep_zero in [False,True]:
            with self.subTest(zero_record=keep_zero):
                self.page.evaluate("""keepZero => {
                  const m=homeMonth(),previous=previousMonthKey(m);
                  state.entries=[{id:'selected',type:'expense',date:m+'-02',amount:10,
                    category:'Продукты',who:'Общее'}];
                  if(keepZero)state.entries.push({id:'zero-legacy',type:'expense',date:previous+'-02',
                    amount:0,category:'Продукты',who:'Общее',futureField:'retain zero'});
                  renderAll();go('home');
                }""",keep_zero)
                before=self.snapshot()
                comparison=self.page.locator('[data-month-review-card="comparison"]')
                self.assertNotIn('%',comparison.inner_text())
                self.assertIn('Процентное сравнение',comparison.inner_text())
                self.assertEqual(self.snapshot(),before)

    def test_largest_group_action_opens_exact_selected_month_and_keeps_equal_amount_records(self):
        self.prepare()
        self.page.evaluate("""() => {
          const m=homeMonth();state.entries[0].amount=50.50;state.entries[1].amount=50.50;
          renderAll();go('home');
        }""")
        before=self.snapshot()
        self.assertIn('101,00',self.page.locator('#v96MonthlyLargestAmount').inner_text())
        self.page.locator('#v96MonthlyReview').get_by_role('button',name='Открыть расходы группы '+self.info['group'],exact=True).click()
        self.assertTrue(self.page.locator('#v84DrillModal').is_visible())
        self.assertEqual(self.page.evaluate('v96DrillContext.month'),self.info['chosen'])
        self.assertEqual(self.page.locator('#v84DrillEntries .v85-drill-entry').count(),2)
        rows=self.page.locator('#v84DrillEntries').inner_text()
        self.assertIn('Fictional old-first',rows);self.assertIn('Fictional old-second',rows)
        self.assertNotIn('current-expense',rows)
        self.assertEqual(self.snapshot(),before)

    def test_always_visible_in_short_and_full_overview_and_responsive_without_writes(self):
        self.prepare()
        self.assertEqual(self.page.locator('#home .smart-insights').count(),0)
        for focused in [True,False]:
            self.page.evaluate('(on)=>document.getElementById("home").classList.toggle("v73-focus",on)',focused)
            self.assertTrue(self.page.locator('#v96MonthlyReview').is_visible())
        for width in [320,390,1280]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':900})
                sizes=self.page.locator('#v96MonthlyReview').evaluate("""root => ({
                  viewport:innerWidth,right:root.getBoundingClientRect().right,
                  columns:getComputedStyle(root.querySelector('.v96-month-review-grid')).gridTemplateColumns.split(' ').length,
                  cards:[...root.querySelectorAll('[data-month-review-card]')].map(x=>x.getBoundingClientRect().width)
                })""")
                self.assertLessEqual(sizes['right'],width+1)
                self.assertEqual(sizes['columns'],1 if width<=760 else 3)
                self.assertTrue(all(size<=width for size in sizes['cards']))
        self.page.evaluate('v84RenderAll();renderTodayAdvice();renderHome()')
        self.assertEqual(self.snapshot(),self.before)


if __name__=='__main__':
    unittest.main()
