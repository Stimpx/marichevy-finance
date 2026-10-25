"""Synthetic regressions for edited payment identities and durable queue safety."""
import unittest
import test_local_data_safety as harness


class FinancialFollowup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        harness.LocalDataSafety.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        harness.LocalDataSafety.tearDownClass.__func__(cls)

    setUp = harness.LocalDataSafety.setUp
    tearDown = harness.LocalDataSafety.tearDown
    open = harness.LocalDataSafety.open

    def evaluate(self, code):
        self.open()
        return self.page.evaluate('''async () => {
          session=null;state=blankState();localStorage.clear();showApp();
          window.confirm=()=>true;window.prompt=()=> '1';
          const mk=(id,type='expense')=>({id,type,date:today(),amount:1250.50,
            category:'Прочее',who:'Виктория',store:'Fictional shop'});
          const snapshot=()=>({memory:JSON.stringify(state),
            primary:localStorage.getItem(KEYS.state),pending:localStorage.getItem(KEYS.pending)});
          const lastNotice=()=>[...document.body.children].findLast(el=>el.style.zIndex==='200')?.textContent||'';
          const editToIncome=async(id)=>{openEdit(id);xType.value='income';xWho.value='Виктория';await saveEdit()};
        ''' + code + '\n}')

    def test_today_history_displays_subruble_expense_without_rounding_to_zero(self):
        result=self.evaluate("""
          state.entries=[{...mk('fictional-49-kopecks'),amount:0.49}];
          const before=JSON.stringify(state.entries);renderToday();
          return {before,after:JSON.stringify(state.entries),shown:document.querySelector('#todayList strong').textContent};
        """)
        self.assertEqual(result['before'],result['after'])
        self.assertIn('0,49',result['shown'])

    def test_visible_month_total_retains_kopecks_and_excludes_transfer(self):
        result=self.evaluate("""
          state.entries=[{...mk('fictional-ten-kopecks'),amount:0.10},
            {...mk('fictional-twenty-kopecks'),amount:0.20},
            {...mk('fictional-transfer','transfer'),amount:100},
            {...mk('fictional-income','income'),amount:1}];
          const before=JSON.stringify(state.entries);document.getElementById('homeMonth').value=month();renderHome();
          return {before,after:JSON.stringify(state.entries),expenseIds:expenses(month()).map(e=>e.id),
            shown:document.querySelector('#monthCompare .compare-value').textContent,
            balance:document.querySelectorAll('#monthCompare .compare-value')[1].textContent};
        """)
        self.assertEqual(result['before'],result['after'])
        self.assertEqual(result['expenseIds'],['fictional-ten-kopecks','fictional-twenty-kopecks'])
        self.assertIn('0,30',result['shown'])
        self.assertIn('0,70',result['balance'])

    def test_exact_cent_budget_boundary_does_not_claim_false_overspend(self):
        result=self.evaluate("""
          state.entries=[{...mk('fictional-a'),category:'Продукты',amount:0.10},
            {...mk('fictional-b'),category:'Продукты',amount:0.20},
            {...mk('fictional-transfer','transfer'),category:'Продукты',amount:99}];
          state.intelligence.budgets=[{id:'fictional-budget',group:expenseGroup('Продукты'),amount:0.30}];
          document.getElementById('analyticsMonth').value=month();
          const before=JSON.stringify(state.entries);v84RenderBudgets();
          const visible=document.getElementById('v84BudgetList').textContent,report=v84ReportText();
          const unchanged=before===JSON.stringify(state.entries);
          state.entries.push({...mk('fictional-one-more-kopeck'),category:'Продукты',amount:0.01});
          v84RenderBudgets();
          return {visible,report,unchanged,overspent:document.getElementById('v84BudgetList').textContent};
        """)
        self.assertTrue(result['unchanged'])
        self.assertNotIn('лимит превышен',result['visible'])
        self.assertNotIn('· превышено',result['report'])
        self.assertIn('лимит превышен',result['overspent'])

    def test_edited_partial_recurring_payment_keeps_actual_allocation_and_remaining_forecast(self):
        result=self.evaluate("""
          const recurring={id:'fictional-recurring',name:'Fictional subscription',amount:1250.50,
            category:'Продукты',who:'Виктория',day:1};
          state.intelligence.recurring=[recurring];await v84ConfirmRecurring(recurring.id,month());
          openEdit(state.entries[0].id);xAmount.value='100,25';await saveEdit();
          const historyBefore=JSON.stringify(state.entries);
          const event=v86CalendarEvents(month()).find(e=>e.kind==='regular'&&e.recurringId===recurring.id);
          document.getElementById('v86CalendarMonth').value=month();v86RenderCalendar();
          return {historyBefore,historyAfter:JSON.stringify(state.entries),event,
            remaining:v86Forecast().regular,
            row:[...document.querySelectorAll('#v86CalendarList .v86-calendar-row')].find(e=>e.textContent.includes('Fictional subscription'))?.textContent};
        """)
        self.assertEqual(result['historyBefore'],result['historyAfter'])
        self.assertFalse(result['event']['paid'])
        self.assertEqual(result['event']['allocated'],100.25)
        self.assertEqual(result['remaining'],1150.25)
        self.assertIn('Частично',result['row'])

    def check_installment_edit(self, *, generated):
        result=self.evaluate('''
          const plan={id:'fictional-plan',kind:'personal',title:'Fictional loan',amount:1250.50,
            accountingMode:'payments',parts:[{id:'fictional-part',date:today(),amount:1250.50}],links:{}};
          state.installments=[plan];
        ''' + ('''
          v77PayPart(plan.id,plan.parts[0].id);v77PayPart(plan.id,plan.parts[0].id);
        ''' if generated else '''
          state.entries=[mk('fictional-linked-history')];
          v77LinkPayment(plan.id,plan.parts[0].id,state.entries[0].id);
        ''') + '''
          const initialCount=state.entries.length;
          await editToIncome(state.entries[0].id);
          const before=snapshot();
          v77PayPart(plan.id,plan.parts[0].id);
          await Promise.resolve();
          return {initialCount,before,after:snapshot(),message:lastNotice()};
        ''')
        self.assertEqual(result['initialCount'],1)
        self.assertEqual(result['after'],result['before'])
        self.assertIn('изменена',result['message'].lower())

    def test_reconfirm_edited_generated_installment_preserves_memory_primary_and_pending(self):
        self.check_installment_edit(generated=True)

    def test_reconfirm_edited_manually_linked_installment_requires_review(self):
        self.check_installment_edit(generated=False)

    def check_recurring_edit(self, *, generated):
        result=self.evaluate('''
          const recurring={id:'fictional-recurring',name:'Fictional subscription',amount:1250.50,
            category:'Продукты',who:'Виктория',day:1};
          state.intelligence.recurring=[recurring];
        ''' + ('''
          await v84ConfirmRecurring(recurring.id,month());
          await v84ConfirmRecurring(recurring.id,month());
        ''' if generated else '''
          state.entries=[{...mk('fictional-linked-history'),recurringId:recurring.id,recurringPeriod:month()}];
          await saveAll();
        ''') + '''
          const initialCount=state.entries.length;
          await editToIncome(state.entries[0].id);
          const before=snapshot();
          await v84ConfirmRecurring(recurring.id,month());
          await Promise.resolve();
          return {initialCount,before,after:snapshot(),message:lastNotice()};
        ''')
        self.assertEqual(result['initialCount'],1)
        self.assertEqual(result['after'],result['before'])
        self.assertIn('изменена',result['message'].lower())

    def test_reconfirm_edited_generated_recurring_preserves_memory_primary_and_pending(self):
        self.check_recurring_edit(generated=True)

    def test_reconfirm_edited_linked_recurring_requires_review(self):
        self.check_recurring_edit(generated=False)

    def test_invalid_duplicate_state_cannot_overwrite_last_valid_pending_queue(self):
        result=self.evaluate('''
          state.entries=[mk('fictional-unique')];await saveAll();
          const before={primary:localStorage.getItem(KEYS.state),pending:localStorage.getItem(KEYS.pending)};
          state.entries.push({...state.entries[0],amount:99.01});
          const memory=JSON.stringify(state),ok=savePendingLocal();
          return {ok,before,after:{primary:localStorage.getItem(KEYS.state),pending:localStorage.getItem(KEYS.pending)},
            memoryUnchanged:memory===JSON.stringify(state),storageFailed:v89StorageFailed,
            status:document.getElementById('syncStatus').textContent};
        ''')
        self.assertFalse(result['ok'])
        self.assertEqual(result['after'],result['before'])
        self.assertTrue(result['memoryUnchanged'])
        self.assertTrue(result['storageFailed'])
        self.assertIn('Не удалось',result['status'])


if __name__=='__main__':
    unittest.main()
