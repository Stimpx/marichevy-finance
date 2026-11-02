"""Russian monetary typing and explicit saves; fictional data, no cloud or messages."""
import json
import unittest

import test_local_data_safety as harness


class MoneyInputsConsistency(unittest.TestCase):
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

    def prepare(self, tab='goals'):
        self.open()
        self.page.evaluate("""tab => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          telegramNotify=()=>Promise.resolve(false);
          state.futureTop={preserve:[true,null,'fictional']};
          state.entries=[{id:'fictional-history',type:'expense',date:'2026-10-21',
            amount:17.251,category:'Historical category',who:'Historical recipient',
            futureField:{original:'unchanged'}}];
          state.goals=[{id:'fictional-goal',name:'Старая вымышленная цель',target:9000,
            saved:17.251,monthly:2.25,deposits:[{id:'fictional-deposit',amount:17.251,
              date:'2026-10-21',futureField:'original'}],futureField:{original:true}}];
          const data=v84Data();
          data.accounts=[{id:'fictional-account',name:'Старый вымышленный счёт',
            amount:-17.25,updated_at:'2026-10-21T00:00:00Z',futureField:{original:true}}];
          data.budgets=[{id:'fictional-budget',group:'Historical budget',amount:17.25,
            futureField:{original:true}}];
          data.recurring=[{id:'fictional-recurring',name:'Historical recurring',
            amount:17.25,category:'Прочее',day:2,futureField:{original:true}}];
          data.futureField={preserve:['fictional']};
          state.settings.preferences.futureField={original:true};
          showApp();renderAll();go(tab);
          window.__moneyWrites={saves:0,pending:0};
          const originalSave=saveAll,originalSet=Storage.prototype.setItem;
          saveAll=function(...args){window.__moneyWrites.saves++;return originalSave(...args)};
          Storage.prototype.setItem=function(key,value){
            if(key===KEYS.pending)window.__moneyWrites.pending++;
            return originalSet.call(this,key,value);
          };
        }""", tab)
        if tab == 'goals':
            self.page.get_by_role('button', name='Новая цель', exact=True).click()
        self.original = self.page.evaluate('JSON.parse(JSON.stringify(state))')

    def type_money(self, selector, text):
        field = self.page.locator(selector)
        self.assertEqual(field.get_attribute('type'), 'text', selector)
        self.assertEqual(field.get_attribute('inputmode'), 'decimal', selector)
        field.fill('')
        field.press_sequentially(text)
        self.assertEqual(field.input_value(), text, 'Browser must preserve every typed separator')

    def writes(self):
        return self.page.evaluate('window.__moneyWrites')

    def saved_state(self):
        saved = self.page.evaluate("""() => ({state:JSON.parse(JSON.stringify(state)),
          pending:JSON.parse(localStorage.getItem(KEYS.pending))})""")
        self.assertEqual(saved['pending'], saved['state'])
        self.assertEqual(saved['state']['entries'], self.original['entries'])
        self.assertEqual(saved['state']['futureTop'], self.original['futureTop'])
        self.assertEqual(saved['state']['intelligence']['futureField'],
                         self.original['intelligence']['futureField'])
        return saved['state']

    def goal_button(self):
        return self.page.locator('.goal-create').get_by_role('button', name='Создать цель', exact=True)

    def configure_goal(self):
        if not self.page.locator('#v119GoalCreate').evaluate('(el)=>el.open'):
            self.page.get_by_role('button', name='Новая цель', exact=True).click()
        self.page.locator('#goalName').fill('Вымышленная новая цель')
        self.page.locator('#goalTarget').fill('5000')
        self.page.locator('#goalSaved').fill('0')
        self.page.locator('#goalMonthly').fill('0')

    def configure_installment(self):
        self.page.evaluate("go('loans')")
        self.page.locator('#v77NewInstallmentBtn').click()
        self.page.locator('#v77Purchase').fill('Вымышленная покупка')
        self.page.locator('#v77Provider').fill('Учебный магазин')
        self.page.locator('#v77PartCount').fill('3')
        self.page.locator('#v77FirstDate').fill('2026-11-15')

    def open_surface(self, tab, selector):
        if selector == '#v84AccountAmount':
            tab = 'accounts'
        elif selector in ('#v84BudgetAmount', '#v84RecAmount'):
            tab = 'planning'
        self.page.evaluate('(tab)=>go(tab)', tab)
        if selector == '#v84BudgetAmount':
            details = self.page.locator('#v118LegacyLimits').locator('..')
            if not details.evaluate('(el)=>el.open'):
                details.locator('summary').click()

    def test_typed_goal_fields_save_once_in_exact_kopecks_and_keep_legacy_rows(self):
        self.prepare()
        self.page.locator('#goalName').fill('Вымышленная новая цель')
        self.type_money('#goalTarget', '1 250,50')
        self.type_money('#goalSaved', '125,25')
        self.type_money('#goalMonthly', '1\u00a0000.05')
        self.assertEqual(self.writes(), {'saves': 0, 'pending': 0})
        self.goal_button().click()
        saved = self.saved_state()
        self.assertEqual(self.writes(), {'saves': 1, 'pending': 1})
        self.assertEqual(len(saved['goals']), 2)
        self.assertEqual(saved['goals'][0], self.original['goals'][0])
        self.assertEqual([saved['goals'][1][key] for key in ('target', 'saved', 'monthly')],
                         [1250.50, 125.25, 1000.05])
        self.assertEqual(saved['intelligence'], self.original['intelligence'])

    def test_optional_empty_goal_values_and_fractional_deposit_preserve_exact_cents(self):
        self.prepare()
        self.page.locator('#goalName').fill('Цель с копейками')
        self.type_money('#goalTarget', '1 250,50')
        self.type_money('#goalSaved', '0,10')
        # Empty optional monthly contribution is exactly zero.
        self.page.locator('#goalMonthly').fill('')
        self.goal_button().click()
        identifier = self.page.evaluate('state.goals.at(-1).id')
        self.type_money('#deposit_' + identifier, '0,20')
        self.page.locator('#deposit_' + identifier).locator('..').get_by_role(
            'button', name='Добавить', exact=True).click()
        saved = self.saved_state()
        self.assertEqual(self.writes(), {'saves': 2, 'pending': 2})
        goal = saved['goals'][-1]
        self.assertEqual((goal['saved'], goal['monthly']), (0.30, 0))
        self.assertEqual([item['amount'] for item in goal['deposits']], [0.20])
        self.assertEqual(saved['goals'][0], self.original['goals'][0])
        self.page.get_by_role('button', name='Новая цель', exact=True).click()
        self.page.locator('#goalName').fill('Цель без начальных накоплений')
        self.type_money('#goalTarget', '10,01')
        self.goal_button().click()
        self.assertEqual([self.saved_state()['goals'][-1][key] for key in ('saved', 'monthly')], [0, 0])

    def test_manual_account_create_negative_update_and_zero_keep_other_rows_and_extensions(self):
        self.prepare('accounts')
        self.page.locator('#v84AccountName').fill('Вымышленный кошелёк')
        self.type_money('#v84AccountAmount', '1 250,50')
        self.page.locator('#v84AccountSave').click()
        saved = self.saved_state()
        self.assertEqual(self.writes(), {'saves': 1, 'pending': 1})
        self.assertEqual(len(saved['intelligence']['accounts']), 2)
        self.assertEqual(saved['intelligence']['accounts'][1]['amount'], 1250.50)
        self.assertEqual(saved['intelligence']['accounts'][0], self.original['intelligence']['accounts'][0])
        # Edit through the existing row action; unknown fields on the edited record survive too.
        self.page.locator('#v84AccountsList .v117-account-card').filter(
            has=self.page.get_by_text('Старый вымышленный счёт', exact=True)
        ).get_by_role('button', name='Изменить снимок', exact=True).click()
        self.type_money('#v84AccountAmount', '-1\u202f250,50')
        self.page.locator('#v84AccountSave').click()
        saved = self.saved_state()
        self.assertEqual(self.writes(), {'saves': 2, 'pending': 2})
        accounts = saved['intelligence']['accounts']
        self.assertEqual(len(accounts), 2)
        self.assertEqual(accounts[0]['amount'], -1250.50)
        self.assertEqual(accounts[0]['futureField'], {'original': True})
        self.assertEqual(accounts[1]['amount'], 1250.50)
        self.page.locator('#v84AccountName').fill('Вымышленный нулевой счёт')
        self.type_money('#v84AccountAmount', '0,00')
        self.page.locator('#v84AccountSave').click()
        self.assertEqual(self.saved_state()['intelligence']['accounts'][-1]['amount'], 0)
        self.assertEqual(self.writes(), {'saves': 3, 'pending': 3})

    def test_budget_recurring_reserve_and_purchase_use_the_same_typed_amount(self):
        self.prepare('analytics')
        self.open_surface('planning', '#v84BudgetAmount')
        self.type_money('#v84BudgetAmount', '1 250,50')
        self.page.locator('#v84BudgetsCard').get_by_role('button', name='Установить', exact=True).click()
        saved = self.saved_state()
        self.assertEqual(saved['intelligence']['budgets'][-1]['amount'], 1250.50)
        self.assertEqual(saved['intelligence']['budgets'][0], self.original['intelligence']['budgets'][0])
        self.page.locator('#v84RecName').fill('Вымышленная подписка')
        self.type_money('#v84RecAmount', '1\u00a0250.50')
        self.page.locator('#v84RecurringsCard').get_by_role('button', name='Добавить в план', exact=True).click()
        saved = self.saved_state()
        self.assertEqual(saved['intelligence']['recurring'][-1]['amount'], 1250.50)
        self.assertEqual(saved['intelligence']['recurring'][0], self.original['intelligence']['recurring'][0])
        self.open_surface('analytics', '#v87Reserve')
        self.type_money('#v87Reserve', '1\u202f250,50')
        self.page.locator('#v87AdvisorCard').get_by_role('button', name='Пересчитать', exact=True).click()
        saved = self.saved_state()
        self.assertEqual(saved['settings']['preferences']['advisorReserve'], 1250.50)
        self.assertEqual(saved['settings']['preferences']['futureField'], {'original': True})
        self.configure_installment()
        self.type_money('#v77PurchaseSum', '1 250,50')
        self.page.locator('#v77SaveInstallmentBtn').click()
        saved = self.saved_state()
        self.assertEqual(len(saved['installments']), 1)
        self.assertEqual(saved['installments'][0]['amount'], 1250.50)
        self.assertEqual([part['amount'] for part in saved['installments'][0]['parts']], [416.83, 416.83, 416.84])
        self.assertEqual(self.writes(), {'saves': 4, 'pending': 4})
        self.assertEqual(saved['goals'], self.original['goals'])
        self.assertEqual(saved['intelligence']['accounts'], self.original['intelligence']['accounts'])

    def test_early_repayment_accepts_cents_as_draft_without_any_financial_write(self):
        self.prepare('loans')
        self.page.get_by_role('button', name='＋ Добавить досрочный платёж', exact=True).click()
        self.type_money('.early-plan-amount', '1 250,50')
        self.page.locator('.early-plan-date').fill('2026-11-15')
        before = self.snapshot()
        self.page.get_by_role('button', name='Рассчитать весь план', exact=True).click()
        self.assertEqual(self.page.evaluate('getEarlyPayments()'), [{'amount': 1250.50, 'date': '2026-11-15'}])
        self.assertEqual(self.page.locator('#earlyResult .early-grid').count(), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.writes(), {'saves': 0, 'pending': 0})

    def test_malformed_money_in_every_save_surface_is_rejected_without_any_write(self):
        self.prepare()
        malformed = ('1,234', '1.2.3', '1e3', 'Infinity', 'NaN', '1 2',
                     '1 250,5.0', '90071992547409,91')
        surfaces = (
            ('goals', '#goalTarget', '#v119GoalSubmit'),
            ('goals', '#goalSaved', '#v119GoalSubmit'),
            ('goals', '#goalMonthly', '#v119GoalSubmit'),
            ('settings', '#v84AccountAmount', '#v84AccountSave'),
            ('analytics', '#v84BudgetAmount', '[onclick="v84AddBudget()"]'),
            ('analytics', '#v84RecAmount', '[onclick="v84AddRecurring()"]'),
            ('analytics', '#v87Reserve', '[onclick="v87ApplyAdvisor()"]'),
            ('loans', '#v77PurchaseSum', '#v77SaveInstallmentBtn'),
        )
        for tab, selector, button in surfaces:
            self.open_surface(tab, selector)
            if tab == 'goals':
                self.configure_goal()
            elif selector == '#v84AccountAmount':
                self.page.locator('#v84AccountName').fill('Недопустимый вымышленный счёт')
            elif selector == '#v84RecAmount':
                self.page.locator('#v84RecName').fill('Недопустимый вымышленный план')
            elif selector == '#v77PurchaseSum':
                self.configure_installment()
            before = self.snapshot()
            for value in malformed:
                with self.subTest(field=selector, value=value):
                    self.type_money(selector, value)
                    self.page.locator(button).click()
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(self.writes(), {'saves': 0, 'pending': 0})
                    self.assertTrue(self.page.locator(selector).evaluate('(el)=>!!el.validationMessage'))

    def test_required_sign_and_range_validation_prevents_empty_zero_negative_or_excessive_save(self):
        self.prepare()
        cases = (
            ('goals', '#goalTarget', '#v119GoalSubmit', ('', '0', '-1')),
            ('goals', '#goalSaved', '#v119GoalSubmit', ('-1', '5000,01')),
            ('goals', '#goalMonthly', '#v119GoalSubmit', ('-1',)),
            ('settings', '#v84AccountAmount', '#v84AccountSave', ('', '1000000000000,01', '-1000000000000,01')),
            ('analytics', '#v84BudgetAmount', '[onclick="v84AddBudget()"]', ('', '0', '-1', '1000000000,01')),
            ('analytics', '#v84RecAmount', '[onclick="v84AddRecurring()"]', ('', '0', '-1', '1000000000,01')),
            ('analytics', '#v87Reserve', '[onclick="v87ApplyAdvisor()"]', ('-1', '100000000,01')),
            ('loans', '#v77PurchaseSum', '#v77SaveInstallmentBtn', ('', '0', '-1', '100000000,01')),
        )
        for tab, selector, button, values in cases:
            self.open_surface(tab, selector)
            if tab == 'goals':
                self.configure_goal()
            elif selector == '#v84AccountAmount':
                self.page.locator('#v84AccountName').fill('Недопустимый счёт')
            elif selector == '#v84RecAmount':
                self.page.locator('#v84RecName').fill('Недопустимый план')
            elif selector == '#v77PurchaseSum':
                self.configure_installment()
            before = self.snapshot()
            for value in values:
                with self.subTest(field=selector, value=value):
                    self.page.locator(selector).fill(value)
                    self.page.locator(button).click()
                    self.assertEqual(self.snapshot(), before)
                    self.assertEqual(self.writes(), {'saves': 0, 'pending': 0})

    def test_deposit_and_early_repayment_invalid_amounts_never_write_or_silently_use_other_rows(self):
        self.prepare()
        before = self.snapshot()
        field = '#deposit_fictional-goal'
        for value in ('', '0', '-1', '1,234', '1e3', '9000'):
            with self.subTest(surface='deposit', value=value):
                self.page.locator(field).fill(value)
                self.page.locator(field).locator('..').get_by_role('button', name='Добавить', exact=True).click()
                self.assertEqual(self.snapshot(), before)
        self.page.evaluate("go('loans')")
        self.page.get_by_role('button', name='＋ Добавить досрочный платёж', exact=True).click()
        self.type_money('.early-plan-amount', '1 250,50')
        self.page.get_by_role('button', name='＋ Добавить досрочный платёж', exact=True).click()
        fields = self.page.locator('.early-plan-amount')
        before = self.snapshot()
        for value in ('-1', '1,234', '1e3', 'Infinity', '90071992547409,91'):
            with self.subTest(surface='early repayment', value=value):
                fields.nth(1).fill(value)
                self.page.get_by_role('button', name='Рассчитать весь план', exact=True).click()
                self.assertEqual(self.page.locator('#earlyResult .early-grid').count(), 0,
                                 'Invalid row must not be silently omitted from a calculated plan')
                self.assertTrue(fields.nth(1).evaluate('(el)=>!!el.validationMessage'))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.writes(), {'saves': 0, 'pending': 0})

    def test_optional_reserve_clears_to_zero_and_nonmoney_counts_keep_numeric_controls(self):
        self.prepare('analytics')
        self.type_money('#v87Reserve', '1 250,50')
        self.page.locator('#v87AdvisorCard').get_by_role('button', name='Пересчитать', exact=True).click()
        self.page.locator('#v87Reserve').fill('')
        self.page.locator('#v87AdvisorCard').get_by_role('button', name='Пересчитать', exact=True).click()
        self.assertEqual(self.saved_state()['settings']['preferences']['advisorReserve'], 0)
        self.assertEqual(self.writes(), {'saves': 2, 'pending': 2})
        self.assertEqual(self.page.locator('#v77PartCount').get_attribute('type'), 'number')
        self.assertEqual(self.page.locator('[data-setting="preferences.payday"]').get_attribute('type'), 'number')
        self.assertEqual(self.page.locator('#v87CutRate').evaluate('(el)=>el.tagName'), 'SELECT')
        self.assertEqual(self.page.locator('#v84RecDay').evaluate('(el)=>el.tagName'), 'SELECT')


if __name__ == '__main__':
    unittest.main()
