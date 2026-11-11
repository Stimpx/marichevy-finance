"""Filtered history sums and explicit all-time selection on offline records.

Run: python -m unittest discover -s tests -p test_history_totals.py
All external requests are blocked; fixtures contain no real household data.
"""
from pathlib import Path
import os
import shutil
import unittest
from playwright.sync_api import sync_playwright

HTML = (Path(__file__).resolve().parents[1] / 'index.html').read_text()
BASE = 'http://127.0.0.1:9865/'


class HistoryTotals(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser = cls.p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width': 1440, 'height': 1100}, timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda route: route.fulfill(status=200, content_type='text/html', body=HTML) if route.request.url == BASE else route.abort())
        self.page = self.context.new_page()
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.page.on('dialog', lambda dialog: dialog.accept())
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v158HistorySummary==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          localStorage.clear();state=blankState();today=()=> '2026-11-12';month=()=> '2026-11';
          const mk=(id,amount,date,fields={})=>({id,type:'expense',date,amount,category:'Продукты',subcategory:'',beneficiary:'Сергей',who:'Сергей',store:'Магазин А',comment:'Тестовая покупка',pay:'Карта',created_at:date+'T12:00:00.000Z',updated_at:date+'T12:00:00.000Z',...fields});
          state.entries=[mk('first',100.10,'2026-11-01'),mk('second',50.20,'2026-11-02',{store:'Магазин Б'}),mk('other-person',400,'2026-11-02',{beneficiary:'Виктория',who:'Виктория'}),mk('older',200.30,'2026-10-01'),mk('income',1000.25,'2026-11-03',{type:'income',category:'Доход',store:'Зарплата',beneficiary:''}),mk('move',500,'2026-11-03',{type:'transfer',category:'Движение денег',store:'Перевод',from:'Карта',to:'Накопления'}),mk('cash',50,'2026-11-03',{type:'cash',category:'Движение денег',store:'Наличные',from:'Карта',to:'Наличные'}),mk('adjustment',35,'2026-11-03',{type:'transfer',category:'Движение денег',store:'Сверка',balanceAdjustment:true,adjustmentDirection:-1,accountId:'synthetic-account',reconciliationRevision:'synthetic-revision'})];
          showApp();go('history');resetHistoryFilters();document.getElementById('fMonth').value='2026-11';document.getElementById('fWho').value='Сергей';renderHistory();
          window.historyOriginalEntries=JSON.stringify(state.entries);window.historyOriginalSettings=JSON.stringify(state.settings);
          window.historyRead=()=>({totals:Object.fromEntries([...document.querySelectorAll('#v158HistoryTotals [data-v158-total]')].map(e=>[e.dataset.v158Total,e.querySelector('strong').textContent.replaceAll('\\u00a0',' ')])),count:document.getElementById('historyCount').textContent,ids:[...document.querySelectorAll('#historyBody [data-v141-operation-id]')].map(e=>e.dataset.v141OperationId),period:document.getElementById('v158HistoryPeriod').textContent});
          window.historySet=(id,value)=>{const field=document.getElementById(id);field.value=value;field.dispatchEvent(new Event('input',{bubbles:true}));field.dispatchEvent(new Event('change',{bubbles:true}));};
        }''')

    def tearDown(self):
        self.context.close()
        self.assertEqual(self.errors, [])

    def evaluate(self, code):
        return self.page.evaluate('async () => {' + code + '}')

    def test_month_person_mixed_totals_keep_transfers_and_corrections_separate(self):
        result = self.evaluate('''renderHistory();renderHistory();return {shown:historyRead(),entriesUnchanged:JSON.stringify(state.entries)===historyOriginalEntries,settingsUnchanged:JSON.stringify(state.settings)===historyOriginalSettings};''')
        self.assertEqual(result['shown']['totals'], {'expense':'150,30 ₽','income':'1 000,25 ₽','result':'849,95 ₽','transfer':'500,00 ₽','cash':'50,00 ₽','adjustment':'-35,00 ₽'})
        self.assertEqual(len(result['shown']['ids']), 6)
        self.assertIn('ноябрь', result['shown']['period'])
        self.assertTrue(result['entriesUnchanged'])
        self.assertTrue(result['settingsUnchanged'])

    def test_group_category_search_and_type_use_the_same_visible_rows(self):
        result = self.evaluate('''historySet('fGroup',expenseEntryGroup(state.entries[0]));historySet('fCat','Продукты');historySet('fType','expense');historySet('fSearch','магазин а');return historyRead();''')
        self.assertEqual(result['ids'], ['first'])
        self.assertEqual(result['totals'], {'expense':'100,10 ₽'})
        self.assertIn('1 операция', result['count'])

    def test_day_filter_and_empty_search_update_period_and_zero_sum(self):
        result = self.evaluate('''historySet('fDay','2026-11-02');const day=historyRead();historySet('fSearch','несуществующая покупка');return {day,empty:historyRead()};''')
        self.assertEqual(result['day']['ids'], ['second'])
        self.assertEqual(result['day']['totals'], {'expense':'50,20 ₽'})
        self.assertEqual(result['day']['period'], 'За 02.11.2026')
        self.assertEqual(result['empty']['ids'], [])
        self.assertEqual(result['empty']['totals'], {'expense':'0,00 ₽'})

    def test_all_time_button_clears_day_month_and_keeps_other_filters(self):
        self.evaluate("historySet('fType','expense');historySet('fDay','2026-11-02');")
        self.page.locator('#v158HistoryAllTime').click()
        result = self.evaluate("return {...historyRead(),month:document.getElementById('fMonth').value,day:document.getElementById('fDay').value,who:document.getElementById('fWho').value,type:document.getElementById('fType').value,active:document.getElementById('v158HistoryAllTime').getAttribute('aria-pressed')};")
        self.assertEqual(set(result['ids']), {'first','second','older'})
        self.assertEqual(result['totals'], {'expense':'350,60 ₽'})
        self.assertEqual((result['month'],result['day'],result['who'],result['type']), ('','','Сергей','expense'))
        self.assertEqual(result['period'], 'За всё время')
        self.assertEqual(result['active'], 'true')

    def test_calendar_exposes_all_time_to_keyboard_and_preserves_other_calendars(self):
        self.evaluate("historySet('fDay','2026-11-02');")
        self.page.locator('#fMonth').press('F4')
        self.page.locator('#v108CalendarPanel .v108-clear').wait_for(state='visible')
        self.assertEqual(self.page.locator('#v108CalendarPanel .v108-clear').inner_text(), 'За всё время')
        self.page.locator('#v108CalendarPanel .v108-clear').focus()
        self.page.keyboard.press('Enter')
        result = self.evaluate("return {...historyRead(),month:document.getElementById('fMonth').value,day:document.getElementById('fDay').value,who:document.getElementById('fWho').value};")
        self.assertEqual(result['period'], 'За всё время')
        self.assertEqual((result['month'],result['day'],result['who']), ('','','Сергей'))
        self.assertEqual(result['totals']['expense'], '350,60 ₽')
        self.evaluate("openEntry('expense')")
        self.page.locator('#eDate').press('F4')
        self.page.locator('#v108CalendarPanel .v108-clear').wait_for(state='visible')
        self.assertEqual(self.page.locator('#v108CalendarPanel .v108-clear').inner_text(), 'Очистить')

    def test_actual_add_edit_delete_and_undo_refresh_filtered_sum_once(self):
        result = self.evaluate('''
          historySet('fType','expense');openEntry('expense');document.getElementById('eAmount').value='10.10';v90Choose('Продукты');v133ChooseRecipient('eBeneficiary','Сергей');await addEntry();
          const added=state.entries.at(-1);go('history');const afterAdd=historyRead();openEdit(added.id);document.getElementById('xAmount').value='20.20';await saveEdit();go('history');const afterEdit=historyRead();
          await deleteEntry(added.id);const afterDelete=historyRead();await v119UndoDelete();go('history');
          return {afterAdd,afterEdit,afterDelete,afterUndo:historyRead(),originalPreserved:JSON.stringify(state.entries.filter(e=>e.id!==added.id))===historyOriginalEntries};
        ''')
        self.assertEqual(result['afterAdd']['totals'], {'expense':'160,40 ₽'})
        self.assertEqual(result['afterEdit']['totals'], {'expense':'170,50 ₽'})
        self.assertEqual(result['afterDelete']['totals'], {'expense':'150,30 ₽'})
        self.assertEqual(result['afterUndo']['totals'], {'expense':'170,50 ₽'})
        self.assertTrue(result['originalPreserved'])

    def test_movement_only_filter_has_no_fabricated_income_expense_result(self):
        result = self.evaluate("historySet('fType','transfer');return historyRead();")
        self.assertEqual(set(result['ids']), {'move','adjustment'})
        self.assertEqual(result['totals'], {'transfer':'500,00 ₽','adjustment':'-35,00 ₽'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
