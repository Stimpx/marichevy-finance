"""Unified transaction rows preserve records and actions on offline synthetic data.

Run: python -m unittest discover -s tests -p test_unified_operations.py
Requires Playwright and Chromium; all external requests are blocked.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

HTML=(Path(__file__).resolve().parents[1]/'index.html').read_text()
BASE='http://127.0.0.1:9892/'


class UnifiedOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=sync_playwright().start()
        executable=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser=cls.p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.p.stop()

    def setUp(self):
        self.context=self.browser.new_context(viewport={'width':1280,'height':1100},timezone_id='Europe/Moscow',service_workers='block')
        self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=HTML) if route.request.url==BASE else route.abort())
        self.page=self.context.new_page();self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.on('dialog',lambda dialog:dialog.accept())
        self.page.goto(BASE,wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v141OperationRow==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;localStorage.clear();state=blankState();
          today=()=> '2026-11-07';month=()=> '2026-11';
          const mk=(id,amount,fields={})=>({id,type:'expense',date:'2026-11-06',amount,category:'Продукты',subcategory:'Для дома',beneficiary:'Общее',who:'Общее',store:'Тестовый магазин',comment:'Ручная заметка о покупке',pay:'Карта',created_at:'2026-11-07T12:00:00.000Z',updated_at:'2026-11-07T12:00:00.000Z',...fields});
          state.entries=[mk('expense-cent',31.25),mk('income-cent',1234.56,{type:'income',category:'Доход',subcategory:'',beneficiary:'',who:'Виктория',store:'Консультации',comment:'Ручная заметка о доходе'}),mk('car-cent',200.75,{date:'2026-11-05',category:'Авто и транспорт',subcategory:'Парковка',beneficiary:'Автомобиль',who:'Автомобиль',store:'Тестовый паркинг',comment:'Оплата парковки'})];
          showApp();go('today');clearEntry();
          document.getElementById('homeMonth').value='2026-11';document.getElementById('incomeMonth').value='2026-11';document.getElementById('analyticsMonth').value='2026-11';
          renderHome();renderToday();resetHistoryFilters();renderIncome();window.originalUnifiedEntries=JSON.stringify(state.entries);
          window.unifiedRow=(root,id)=>document.querySelector(root+' [data-v141-operation-id="'+id+'"]');
          window.unifiedText=value=>String(value||'').replace(/\\s+/g,' ').trim();
        }''')

    def tearDown(self):
        self.context.close();self.assertEqual(self.errors,[])

    def evaluate(self,js):
        return self.page.evaluate('async () => {'+js+'}')

    def test_record_cents_and_fields_are_consistent_across_lists(self):
        result=self.evaluate('''
          const read=(root,id)=>{const row=unifiedRow(root,id);return row?{text:unifiedText(row.querySelector('.v141-main')?.textContent),amount:unifiedText(row.querySelector('.v141-amount')?.textContent),before:!!(row.querySelector('.v141-amount').compareDocumentPosition(row.querySelector('.v141-actions'))&Node.DOCUMENT_POSITION_FOLLOWING)}:null};
          return {expense:['#recent','#todayList','#historyBody'].map(root=>read(root,'expense-cent')),income:['#recent','#todayList','#historyBody','#incomeList'].map(root=>read(root,'income-cent')),unchanged:JSON.stringify(state.entries)===originalUnifiedEntries};
        ''')
        self.assertTrue(result['unchanged'])
        for row in result['expense']:
            self.assertIsNotNone(row);self.assertEqual(row['amount'],'−31,25 ₽');self.assertTrue(row['before'])
            for text in ['06.11.2026','Для дома','Общее','Ручная заметка о покупке']:
                self.assertIn(text,row['text'])
        for row in result['income']:
            self.assertIsNotNone(row);self.assertEqual(row['amount'],'+1 234,56 ₽');self.assertTrue(row['before'])
            for text in ['06.11.2026','Консультации','Виктория','Ручная заметка о доходе']:
                self.assertIn(text,row['text'])
        for width in [320,390,768,1280,1920]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':1100})
                self.page.evaluate("go('today')")
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>document.documentElement.clientWidth+1'))
                self.assertFalse(self.page.evaluate("[...document.querySelectorAll('#todayList .v141-operation')].some(row=>row.scrollWidth>row.clientWidth+1)"))

    def test_user_text_is_escaped_without_mutating_records(self):
        result=self.evaluate('''
          const row=state.entries[0];row.store='<img src=x onerror="window.badUnified=1">';row.comment='<script>window.badUnified=2</script>';const original=JSON.stringify(row);
          renderToday();resetHistoryFilters();const shown=unifiedRow('#todayList',row.id),history=unifiedRow('#historyBody',row.id);
          return {title:shown.querySelector('.v141-main').textContent,history:history.textContent,unsafe:!!shown.querySelector('[onerror],[onload],script'),bad:window.badUnified||0,unchanged:JSON.stringify(row)===original};
        ''')
        self.assertIn('<img src=x onerror=',result['title']);self.assertIn('<script>',result['history'])
        self.assertFalse(result['unsafe']);self.assertEqual(result['bad'],0);self.assertTrue(result['unchanged'])

    def test_history_filter_edit_and_viewer_delete_keep_existing_handlers(self):
        self.page.evaluate("go('history');document.getElementById('fSearch').value='Ручная заметка о покупке';renderHistory()")
        self.assertEqual(self.page.locator('#historyBody .v141-operation').count(),1)
        self.page.locator('#historyBody [data-action="edit"][data-id="expense-cent"]').click()
        self.assertEqual(self.page.locator('#xAmount').input_value(),'31.25')
        self.page.evaluate("closeEdit();window.__FINANCE_BRIDGE__={active:true,role:'viewer'}")
        self.page.locator('#historyBody [data-action="delete"][data-id="expense-cent"]').click()
        self.assertTrue(self.evaluate('return JSON.stringify(state.entries)===originalUnifiedEntries;'))

    def test_repeat_button_fills_draft_and_saves_manual_comment_without_changing_original(self):
        self.page.locator('#todayList [data-v141-operation-id="expense-cent"] [data-record-action="entry-repeat"]').click()
        self.assertEqual(self.page.locator('#eAmount').input_value().replace(',','.'),'31.25')
        self.assertEqual(self.page.locator('#eComment').input_value(),'Ручная заметка о покупке')
        self.page.locator('#v90Save').click()
        self.page.wait_for_function('state.entries.length===4&&!v90Saving')
        result=self.evaluate("return {saved:state.entries.at(-1),original:JSON.stringify(state.entries.slice(0,3))===originalUnifiedEntries,rows:document.querySelectorAll('#todayList .v141-operation').length};")
        self.assertEqual(result['saved']['amount'],31.25);self.assertEqual(result['saved']['comment'],'Ручная заметка о покупке')
        self.assertEqual(result['saved']['date'],'2026-11-07');self.assertTrue(result['original']);self.assertEqual(result['rows'],4)

    def test_drill_edit_preserves_return_context_and_recalculates_totals(self):
        self.page.evaluate("go('analytics');v84Drill('person','Автомобиль','analytics')")
        self.page.locator('#v84DrillEntries [data-record-action="drill-entry-edit"]').click()
        self.assertEqual(self.page.locator('#xAmount').input_value(),'200.75')
        self.page.locator('#xAmount').fill('250,25')
        self.page.evaluate('async () => {await saveEdit()}')
        self.page.wait_for_function("document.getElementById('v84DrillModal').classList.contains('open')&&!document.getElementById('editModal').classList.contains('open')")
        result=self.evaluate("return {context:{mode:v96DrillContext.mode,key:v96DrillContext.key,month:v96DrillContext.month},total:unifiedText(document.getElementById('v96DrillTotal').textContent),row:unifiedText(unifiedRow('#v84DrillEntries','car-cent').querySelector('.v141-amount').textContent),count:state.entries.length};")
        self.assertEqual(result['context'],{'mode':'person','key':'Автомобиль','month':'2026-11'})
        self.assertEqual(result['total'],'250,25 ₽');self.assertEqual(result['row'],'−250,25 ₽');self.assertEqual(result['count'],3)

    def test_specialized_link_toolbar_links_existing_record_without_duplicate(self):
        self.evaluate("state.intelligence.recurring.push({id:'unified-recurring',name:'Покупка по плану',amount:31.25,day:7,category:'Продукты'});v84LinkRecurring('unified-recurring','2026-11');")
        row=self.page.locator('#v84DrillBody [data-v141-operation-id="expense-cent"]')
        self.assertEqual(row.count(),1)
        self.assertEqual(row.locator('[data-v84-link="expense-cent"]').count(),1)
        self.assertEqual(row.locator('.v112-record-action').count(),0)
        row.locator('[data-v84-link="expense-cent"]').click()
        result=self.evaluate("const e=state.entries.find(row=>row.id==='expense-cent');return {count:state.entries.length,amount:e.amount,date:e.date,comment:e.comment,linked:e.recurringId,period:e.recurringPeriod};")
        self.assertEqual(result,{'count':3,'amount':31.25,'date':'2026-11-06','comment':'Ручная заметка о покупке','linked':'unified-recurring','period':'2026-11'})

    def test_account_adjustment_rows_keep_direction_signs_without_regular_actions(self):
        result=self.evaluate('''
          state.entries.push({id:'adjust-plus',type:'transfer',balanceAdjustment:true,adjustmentDirection:1,accountId:'unified-account',amount:12.34,date:'2026-11-05',comment:'Положительная сверка'},{id:'adjust-minus',type:'transfer',balanceAdjustment:true,adjustmentDirection:-1,accountId:'unified-account',amount:56.78,date:'2026-11-06',comment:'Отрицательная сверка'});
          const account={id:'unified-account',ledger:{startDate:'2026-11-01'}},item={account,name:'Тестовый счёт',kind:'asset',enabled:true,includeInSpending:true,balance:0,snapshot:0,difference:0,warnings:[],opening:0,snapshotTrusted:false};
          const mount=document.createElement('div');mount.innerHTML=v117AccountCard(item);document.body.append(mount);
          return {plus:unifiedText(mount.querySelector('[data-v141-operation-id="adjust-plus"] .v141-amount')?.textContent),minus:unifiedText(mount.querySelector('[data-v141-operation-id="adjust-minus"] .v141-amount')?.textContent),actions:mount.querySelectorAll('.v117-account-log button').length,comment:mount.querySelector('.v117-account-log').textContent};
        ''')
        self.assertEqual(result['plus'],'+12,34 ₽');self.assertEqual(result['minus'],'−56,78 ₽');self.assertEqual(result['actions'],0)
        self.assertIn('Положительная сверка',result['comment']);self.assertIn('Отрицательная сверка',result['comment'])


if __name__=='__main__':unittest.main(verbosity=2)
