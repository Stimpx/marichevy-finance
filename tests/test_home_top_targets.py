"""Home expense targets on isolated, offline synthetic records.

Run: python -m unittest discover -s tests -p test_home_top_targets.py
Playwright/Chromium are required; every external request is blocked.
"""
from pathlib import Path
import os
import shutil
import unittest

from playwright.sync_api import sync_playwright


HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9889/'


class HomeTopTargets(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = (os.environ.get('CHROMIUM_EXECUTABLE')
                      or shutil.which('chromium') or shutil.which('chromium-browser'))
        cls.browser = cls.p.chromium.launch(
            headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(
            viewport={'width': 1280, 'height': 1100},
            timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda route: route.fulfill(
            status=200, content_type='text/html', body=HTML)
            if route.request.url == BASE else route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v149RenderHomeTopTargets==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();
          today=()=> '2026-11-08';month=()=> '2026-11';
          window.targetTestEntry=(id,target,amount,fields={})=>({
            id,type:'expense',date:'2026-11-04',amount,category:'Продукты',
            subcategory:'',beneficiary:target,who:target,store:'Тестовый магазин',
            comment:'Синтетическая запись',pay:'Карта',
            created_at:'2026-11-08T12:00:00.000Z',
            updated_at:'2026-11-08T12:00:00.000Z',...fields});
          state.entries=[
            targetTestEntry('personal-loan','Сергей',500.10,{category:'Кредит'}),
            targetTestEntry('personal-extra','Сергей',.20),
            targetTestEntry('personal-auto','Виктория',400.10,{category:'Авто и транспорт'}),
            targetTestEntry('auto-direction','Автомобиль',300.05),
            targetTestEntry('loan-direction','Кредиты и рассрочки',250.15),
            targetTestEntry('shared-a','Семья',100.10),
            targetTestEntry('shared-b','Общие расходы',100.20),
            targetTestEntry('archived','Антон',150.45),
            targetTestEntry('blank','',90.55),
            targetTestEntry('pet','Макс',80.65),
            targetTestEntry('prior','Алиса',9999.99,{date:'2026-10-04'}),
            targetTestEntry('prior-shared','Общее',1.01,{date:'2026-10-05'}),
            targetTestEntry('future','Майя',1000000,{date:'2026-12-01'}),
            targetTestEntry('income','Дени',10000,{type:'income'}),
            targetTestEntry('transfer','Алиса',90000,{type:'transfer'}),
            targetTestEntry('cash','Майя',80000,{type:'cash'}),
            targetTestEntry('adjustment','Алиса',70000,{
              type:'transfer',balanceAdjustment:true,adjustmentDirection:1})];
          state.settings.preferences={...(state.settings.preferences||{}),
            archivedExpenseDirections:['Антон']};
          state.intelligence.recurring.push({id:'only-plan',name:'Запланированное',
            amount:500000,day:28,category:'Продукты',beneficiary:'Майя'});
          showApp();go('home');
          document.getElementById('homeMonth').value='2026-11';renderHome();
          window.originalTargetLedger=JSON.stringify(state.entries);
          window.originalTargetSettings=JSON.stringify(state.settings);
          window.readHomeTargets=()=>[...document.querySelectorAll(
            '#v149HomeTargetsList .v147-top-row')].map(row=>({
              name:row.querySelector('.v147-top-name').textContent,
              target:row.dataset.v149Target,
              amount:row.querySelector('.v147-top-value').textContent.replaceAll('\\u00a0',' '),
              width:parseFloat(row.querySelector('.v147-top-bar>span').style.width)}));
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_top_five_use_recorded_targets_month_and_exact_cents(self):
        result = self.evaluate('''
          const balance=document.getElementById('v121HomeAvailable').textContent;
          v149RenderHomeTopTargets('2026-11');v149RenderHomeTopTargets('2026-11');
          return {rows:readHomeTargets(),
            unchanged:JSON.stringify(state.entries)===originalTargetLedger,
            settingsUnchanged:JSON.stringify(state.settings)===originalTargetSettings,
            balanceUnchanged:document.getElementById('v121HomeAvailable').textContent===balance};
        ''')
        self.assertEqual([row['name'] for row in result['rows']], [
            'Сергей', 'Виктория', 'Автомобиль', 'Кредиты и рассрочки', 'Общее'])
        self.assertEqual([row['amount'] for row in result['rows']], [
            '500,30 ₽', '400,10 ₽', '300,05 ₽', '250,15 ₽', '200,30 ₽'])
        self.assertEqual([row['target'] for row in result['rows']],
                         [row['name'] for row in result['rows']])
        self.assertEqual(result['rows'][0]['width'], 100)
        self.assertAlmostEqual(result['rows'][2]['width'], 300.05 / 500.30 * 100, delta=.1)
        self.assertTrue(result['unchanged'])
        self.assertTrue(result['settingsUnchanged'])
        self.assertTrue(result['balanceUnchanged'])

    def test_archived_legacy_pet_blank_and_shared_aliases_each_count_once(self):
        result = self.evaluate('''
          state.entries=[targetTestEntry('archived','Антон',12.10),
            targetTestEntry('legacy','',.20,{who:'Антон'}),
            targetTestEntry('shared-a','Семья / общее',5.10),
            targetTestEntry('shared-b','Общее',5.20),
            targetTestEntry('shared-c','Общие расходы',.10),
            targetTestEntry('blank','',9.90),
            targetTestEntry('pet','Макс',8.80)];
          const before=JSON.stringify(state.entries);renderHome();
          return {rows:readHomeTargets(),totals:v149HomeTopTargets('2026-11'),
            unchanged:JSON.stringify(state.entries)===before};
        ''')
        self.assertEqual([row['name'] for row in result['rows']],
                         ['Антон', 'Общее', 'Не указано', 'Макс'])
        self.assertEqual([row['amount'] for row in result['rows']],
                         ['12,30 ₽', '10,40 ₽', '9,90 ₽', '8,80 ₽'])
        self.assertEqual(sum(round(total * 100) for _, total in result['totals']), 4140)
        self.assertTrue(result['unchanged'])

    def test_fewer_targets_and_empty_month_do_not_invent_zero_rows(self):
        result = self.evaluate('''
          state.entries=[targetTestEntry('one','Алиса',12.25),
            targetTestEntry('two','Дени',5.50),
            targetTestEntry('not-expense','Сергей',10000,{type:'income'})];
          renderHome();const fewer=readHomeTargets();state.entries=[];renderHome();
          return {fewer,emptyRows:readHomeTargets(),
            emptyText:document.getElementById('v149HomeTargetsList').textContent};
        ''')
        self.assertEqual([row['name'] for row in result['fewer']], ['Алиса', 'Дени'])
        self.assertEqual([row['amount'] for row in result['fewer']], ['12,25 ₽', '5,50 ₽'])
        self.assertEqual(result['emptyRows'], [])
        self.assertIn('Расходов за этот месяц пока нет', result['emptyText'])

    def test_actual_month_change_refreshes_targets_without_mutating_history(self):
        result = self.evaluate('''
          const select=document.getElementById('homeMonth');select.value='2026-10';
          select.dispatchEvent(new Event('change',{bubbles:true}));
          return {rows:readHomeTargets(),month:homeMonth(),
            rankingMonth:document.getElementById('v149HomeTopTargets').dataset.month,
            unchanged:JSON.stringify(state.entries)===originalTargetLedger};
        ''')
        self.assertEqual(result['month'], '2026-10')
        self.assertEqual(result['rankingMonth'], '2026-10')
        self.assertEqual([row['name'] for row in result['rows']], ['Алиса', 'Общее'])
        self.assertEqual([row['amount'] for row in result['rows']], ['9 999,99 ₽', '1,01 ₽'])
        self.assertTrue(result['unchanged'])

    def test_actual_add_edit_delete_refresh_targets_and_preserve_balance_calculation(self):
        result = self.evaluate('''
          const beforeAvailable=document.getElementById('v121HomeAvailable').textContent;
          openEntry('expense');document.getElementById('eAmount').value='300';
          v90Choose('Продукты');v133ChooseRecipient('eBeneficiary','Виктория');
          await addEntry();const added=state.entries.at(-1),afterAdd=readHomeTargets();
          openEdit(added.id);document.getElementById('xAmount').value='50';
          await saveEdit();const afterEdit=readHomeTargets(),
            availableAfterEdit=document.getElementById('v121HomeAvailable').textContent,
            expectedAvailable=money2(v111MonthBalance(homeMonth()).closing);
          await deleteEntry(added.id);
          return {afterAdd,afterEdit,afterDelete:readHomeTargets(),
            sameLedger:JSON.stringify(state.entries)===originalTargetLedger,
            sameAvailable:document.getElementById('v121HomeAvailable').textContent===beforeAvailable,
            availableAfterEdit,expectedAvailable};
        ''')
        self.assertEqual(result['afterAdd'][0]['name'], 'Виктория')
        self.assertEqual(result['afterAdd'][0]['amount'], '700,10 ₽')
        self.assertEqual(result['afterEdit'][0]['name'], 'Сергей')
        victoria = next(row for row in result['afterEdit'] if row['name'] == 'Виктория')
        self.assertEqual(victoria['amount'], '450,10 ₽')
        self.assertEqual([row['name'] for row in result['afterDelete']], [
            'Сергей', 'Виктория', 'Автомобиль', 'Кредиты и рассрочки', 'Общее'])
        self.assertEqual(result['availableAfterEdit'], result['expectedAvailable'])
        self.assertTrue(result['sameLedger'])
        self.assertTrue(result['sameAvailable'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
