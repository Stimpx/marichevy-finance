"""Home monthly family totals use saved operations on offline synthetic data.

Run: python -m unittest discover -s tests -p test_home_monthly_cards.py
Requires Playwright and Chromium; every external request is blocked.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

HTML=(Path(__file__).resolve().parents[1]/'index.html').read_text()
BASE='http://127.0.0.1:9890/'


class HomeMonthlyCards(unittest.TestCase):
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
        self.page.wait_for_function("typeof v146RenderHomeMonthly==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;localStorage.clear();state=blankState();
          today=()=> '2026-11-08';month=()=> '2026-11';
          const mk=(id,type,date,amount,who='Общее')=>({id,type,date,amount,category:type==='income'?'Доход':'Продукты',subcategory:'',beneficiary:type==='expense'?who:'',who,store:type==='income'?'Тестовый источник':'Тестовый магазин',comment:'Синтетическая запись',pay:'Карта',created_at:'2026-11-08T12:00:00.000Z',updated_at:'2026-11-08T12:00:00.000Z'});
          state.entries=[mk('prior-income','income','2026-10-10',1000,'Сергей'),mk('prior-expense','expense','2026-10-11',100),mk('sergey-income','income','2026-11-01',100.10,'Сергей'),mk('victoria-income','income','2026-11-02',200.20,'Виктория'),mk('archived-income','income','2026-11-03',50.05,'Алиса'),mk('expense-one','expense','2026-11-04',31.25),mk('expense-two','expense','2026-11-05',68.75),mk('future-income','income','2026-12-01',9999,'Сергей'),{id:'transfer',type:'transfer',date:'2026-11-06',amount:900,from:'Карта',to:'Накопления'},{id:'cash',type:'cash',date:'2026-11-06',amount:800,from:'Карта',to:'Наличные'},{id:'adjustment',type:'transfer',date:'2026-11-06',amount:700,balanceAdjustment:true,adjustmentDirection:1,accountId:'synthetic-account'}];
          state.settings.preferences={...(state.settings.preferences||{}),incomeParticipants:['Сергей','Виктория'],archivedIncomeParticipants:['Алиса']};
          state.intelligence.recurring.push({id:'planned-only',name:'Будущий план',amount:50000,day:28,category:'Дом'});
          showApp();go('home');document.getElementById('homeMonth').value='2026-11';renderHome();
          window.originalMonthlyLedger=JSON.stringify(state.entries);
          window.readHomeMonthly=()=>({income:document.getElementById('v146HomeIncome').textContent.replaceAll('\\u00a0',' '),expense:document.getElementById('v146HomeExpense').textContent.replaceAll('\\u00a0',' '),label:document.getElementById('v146HomeMonthLabel').textContent,incomeWidth:parseFloat(document.getElementById('v146IncomeBar').style.width),expenseWidth:parseFloat(document.getElementById('v146ExpenseBar').style.width)});
        }''')

    def tearDown(self):
        self.context.close();self.assertEqual(self.errors,[])

    def evaluate(self,code):
        return self.page.evaluate('async () => {'+code+'}')

    def test_family_totals_include_archived_earners_and_exclude_nonfinancial_moves(self):
        result=self.evaluate('''return {cards:readHomeMonthly(),expected:v111MonthBalance('2026-11'),archived:!v135IncomePeople().includes('Алиса'),unchanged:JSON.stringify(state.entries)===originalMonthlyLedger};''')
        self.assertEqual(result['cards']['income'],'350,35 ₽');self.assertEqual(result['cards']['expense'],'100,00 ₽')
        self.assertIn('ноябрь',result['cards']['label']);self.assertIn('2026',result['cards']['label'])
        self.assertAlmostEqual(result['expected']['income'],350.35);self.assertAlmostEqual(result['expected']['expense'],100)
        self.assertTrue(result['archived']);self.assertTrue(result['unchanged'])
        self.assertEqual(result['cards']['incomeWidth'],100)
        self.assertAlmostEqual(result['cards']['expenseWidth'],100/350.35*100,delta=.1)

    def test_changing_selected_home_month_updates_both_totals_and_label(self):
        result=self.evaluate('''const select=document.getElementById('homeMonth');select.value='2026-10';select.dispatchEvent(new Event('change',{bubbles:true}));return {cards:readHomeMonthly(),unchanged:JSON.stringify(state.entries)===originalMonthlyLedger};''')
        self.assertEqual(result['cards']['income'],'1 000,00 ₽');self.assertEqual(result['cards']['expense'],'100,00 ₽')
        self.assertIn('октябрь',result['cards']['label']);self.assertEqual(result['cards']['incomeWidth'],100);self.assertEqual(result['cards']['expenseWidth'],10)
        self.assertTrue(result['unchanged'])

    def test_add_edit_and_delete_income_refresh_monthly_cards(self):
        result=self.evaluate('''openEntry('income');document.getElementById('eAmount').value='19,65';document.getElementById('eWho').value='Сергей';document.getElementById('eIncomeSource').value='Тестовое поступление';await addEntry();const added=state.entries.at(-1),afterAdd=readHomeMonthly();openEdit(added.id);document.getElementById('xAmount').value='9,65';await saveEdit();const afterEdit=readHomeMonthly();await deleteEntry(added.id);return {afterAdd,afterEdit,afterDelete:readHomeMonthly(),count:state.entries.length,unchangedOriginal:JSON.stringify(state.entries)===originalMonthlyLedger};''')
        self.assertEqual(result['afterAdd']['income'],'370,00 ₽');self.assertEqual(result['afterEdit']['income'],'360,00 ₽');self.assertEqual(result['afterDelete']['income'],'350,35 ₽')
        for point in ['afterAdd','afterEdit','afterDelete']:self.assertEqual(result[point]['expense'],'100,00 ₽')
        self.assertEqual(result['count'],11);self.assertTrue(result['unchangedOriginal'])

    def test_empty_month_and_expenses_without_income_have_valid_zero_bars(self):
        result=self.evaluate('''state.entries=[];renderHome();const empty=readHomeMonthly();state.entries=[{id:'only-expense',type:'expense',date:'2026-11-04',amount:25.50,category:'Продукты',beneficiary:'Общее',who:'Общее'}];renderHome();return {empty,expenseOnly:readHomeMonthly()};''')
        self.assertEqual(result['empty']['income'],'0,00 ₽');self.assertEqual(result['empty']['expense'],'0,00 ₽')
        self.assertEqual(result['empty']['incomeWidth'],0);self.assertEqual(result['empty']['expenseWidth'],0)
        self.assertEqual(result['expenseOnly']['income'],'0,00 ₽');self.assertEqual(result['expenseOnly']['expense'],'25,50 ₽')
        self.assertEqual(result['expenseOnly']['incomeWidth'],0);self.assertEqual(result['expenseOnly']['expenseWidth'],100)

    def test_monthly_card_rendering_preserves_account_bank_and_ledger(self):
        result=self.evaluate('''const before={available:document.getElementById('v121HomeAvailable').textContent,title:document.getElementById('v121HomeAvailableTitle').textContent,ledger:JSON.stringify(state.entries),settings:JSON.stringify(state.settings)};v146RenderHomeMonthly(v111MonthBalance(homeMonth()));v146RenderHomeMonthly(v111MonthBalance(homeMonth()));const after={available:document.getElementById('v121HomeAvailable').textContent,title:document.getElementById('v121HomeAvailableTitle').textContent,ledger:JSON.stringify(state.entries),settings:JSON.stringify(state.settings)};return {same:JSON.stringify(before)===JSON.stringify(after),available:before.available.replaceAll('\\u00a0',' '),cards:readHomeMonthly()};''')
        self.assertTrue(result['same']);self.assertEqual(result['available'],'—')
        self.assertEqual(result['cards']['income'],'350,35 ₽');self.assertEqual(result['cards']['expense'],'100,00 ₽')

    def test_previous_month_comparisons_use_exact_cents_and_matching_flow_types(self):
        result=self.evaluate('''
          const mk=(id,type,date,amount,fields={})=>({id,type,date,amount,category:'Продукты',...fields});
          state.entries=[mk('oct-a','income','2026-10-01',.10),mk('oct-b','income','2026-10-31',.20),
            mk('nov-a','income','2026-11-01',.40),mk('nov-b','income','2026-11-30',.20),
            mk('oct-food','expense','2026-10-01',.10),mk('oct-credit','expense','2026-10-31',.20,{category:'Кредит'}),
            mk('nov-food','expense','2026-11-01',.10),mk('nov-move','transfer','2026-11-01',900),
            mk('oct-cash','cash','2026-10-01',800),mk('dec-income','income','2026-12-01',999)];
          const before=JSON.stringify(state);v146RenderHomeMonthly(v169HomeBalance('2026-11'));
          return {income:v182ComparisonData(v169HomeBalance('2026-11').income,v169HomeBalance('2026-10').income,'income'),
            expense:v182ComparisonData(v169HomeBalance('2026-11').expense,v169HomeBalance('2026-10').expense,'expense'),
            incomeText:document.getElementById('v182HomeIncomeComparison').textContent,
            expenseText:document.getElementById('v182HomeExpenseComparison').textContent,
            unchanged:JSON.stringify(state)===before};
        ''')
        self.assertEqual((result['income']['current'],result['income']['previous'],result['income']['delta']),(0.6,0.3,0.3))
        self.assertEqual(result['income']['percent'],100);self.assertEqual(result['income']['tone'],'good')
        self.assertEqual((result['expense']['current'],result['expense']['previous'],result['expense']['delta']),(0.1,0.3,-0.2))
        self.assertAlmostEqual(result['expense']['percent'],-200/3);self.assertEqual(result['expense']['tone'],'good')
        self.assertIn('+100%',result['incomeText']);self.assertIn('−66,7%',result['expenseText'])
        self.assertIn('К прошлому месяцу · октябрь 2026',result['incomeText']);self.assertTrue(result['unchanged'])

    def test_previous_calendar_month_rolls_year_and_includes_last_day(self):
        result=self.evaluate('''
          state.entries=[
            {id:'dec-first',type:'income',date:'2025-12-01',amount:20},
            {id:'dec-last',type:'income',date:'2025-12-31',amount:30},
            {id:'jan-income',type:'income',date:'2026-01-31',amount:100},
            {id:'dec-expense',type:'expense',date:'2025-12-31',amount:200,category:'Продукты'},
            {id:'nov-ignore',type:'income',date:'2025-11-30',amount:999}];
          const select=document.getElementById('homeMonth');select.add(new Option('Январь','2026-01'));select.value='2026-01';renderHome();
          return {previous:v182PreviousMonth(v169HomePeriod()),income:document.querySelector('#v182HomeIncomeComparison .v182-month-comparison').outerHTML,
            expense:document.querySelector('#v182HomeExpenseComparison .v182-month-comparison').outerHTML,cards:readHomeMonthly()};
        ''')
        self.assertEqual(result['previous'],'2025-12');self.assertEqual(result['cards']['income'],'100,00 ₽')
        self.assertIn('+100%',result['income']);self.assertIn('декабрь 2025',result['income'])
        self.assertIn('−100%',result['expense']);self.assertIn('data-tone="good"',result['expense'])

    def test_deleted_and_revived_records_match_current_and_previous_report_totals(self):
        result=self.evaluate('''
          const mk=(id,type,date,amount,updated)=>({id,type,date,amount,category:'Продукты',created_at:updated,updated_at:updated});
          state.entries=[mk('prior-live','income','2026-10-01',100,'2026-10-01T12:00:00Z'),
            mk('prior-deleted','income','2026-10-02',1000,'2026-10-02T12:00:00Z'),
            mk('prior-revived','income','2026-10-03',50,'2026-11-01T12:00:00Z'),
            mk('current-live','income','2026-11-01',300,'2026-11-01T12:00:00Z'),
            mk('current-deleted','income','2026-11-02',9000,'2026-11-02T12:00:00Z'),
            mk('prior-expense','expense','2026-10-03',20,'2026-10-03T12:00:00Z'),
            mk('current-expense','expense','2026-11-03',30,'2026-11-03T12:00:00Z')];
          state.deletedEntries={'prior-deleted':'2026-10-03T12:00:00Z','prior-revived':'2026-10-04T12:00:00Z','current-deleted':'2026-11-03T12:00:00Z'};
          v146RenderHomeMonthly(v169HomeBalance('2026-11'));
          const read=id=>document.querySelector('#'+id+' .v182-month-comparison');
          return {incomeText:read('v182HomeIncomeComparison').textContent,incomeTone:read('v182HomeIncomeComparison').dataset.tone,
            expenseText:read('v182HomeExpenseComparison').textContent,expenseTone:read('v182HomeExpenseComparison').dataset.tone};
        ''')
        self.assertIn('+100%',result['incomeText']);self.assertIn('+150,00',result['incomeText']);self.assertEqual(result['incomeTone'],'good')
        self.assertIn('+50%',result['expenseText']);self.assertIn('+10,00',result['expenseText']);self.assertEqual(result['expenseTone'],'bad')

    def test_zero_baseline_and_zero_current_have_no_infinite_percent(self):
        result=self.evaluate('''
          return [[0,0],[10,0],[0,10],[10,10]].map(([current,previous])=>{
            state.entries=[{id:'current',type:'income',date:'2026-11-01',amount:current},
              {id:'previous',type:'income',date:'2026-10-01',amount:previous}];
            v146RenderHomeMonthly(v169HomeBalance('2026-11'));
            const node=document.querySelector('#v182HomeIncomeComparison .v182-month-comparison');
            return {data:v182ComparisonData(current,previous,'income'),change:node.querySelector('.v182-comparison-change').textContent,
              caption:node.querySelector('.v182-comparison-period').textContent,tone:node.dataset.tone};
          });
        ''')
        self.assertEqual([row['data']['percent'] for row in result],[0,None,-100,0])
        self.assertEqual([row['tone'] for row in result],['neutral','good','bad','neutral'])
        self.assertIn('0%',result[0]['change']);self.assertNotIn('%',result[1]['change']);self.assertIn('0 ₽',result[1]['caption'])
        self.assertIn('−100%',result[2]['change']);self.assertIn('0%',result[3]['change'])
        self.assertNotIn('Infinity',str(result));self.assertNotIn('NaN',str(result))

    def test_all_time_clears_previous_comparison_and_month_return_is_fresh(self):
        result=self.evaluate('''
          const nodes=()=>['v182HomeIncomeComparison','v182HomeExpenseComparison'].map(id=>{const node=document.getElementById(id);return {hidden:node.hidden,html:node.innerHTML}});
          const before=nodes();v146RenderHomeMonthly(v169HomeBalance('all'));const all=nodes();
          state.entries.push({id:'september',type:'income',date:'2026-09-30',amount:500});
          v146RenderHomeMonthly(v169HomeBalance('2026-10'));return {before,all,after:nodes(),previous:v182PreviousMonth('all'),invalid:v182PreviousMonth('2026-13')};
        ''')
        self.assertTrue(all(not row['hidden'] for row in result['before']))
        self.assertTrue(all(row['hidden'] and row['html']=='' for row in result['all']))
        self.assertIsNone(result['previous']);self.assertIsNone(result['invalid'])
        self.assertIn('+100%',result['after'][0]['html']);self.assertIn('сентябрь 2026',result['after'][0]['html'])

    def test_small_nonzero_change_is_not_labeled_zero_percent(self):
        result=self.evaluate('''
          return [10000.01,9999.99].map(amount=>{
            state.entries=[{id:'current',type:'income',date:'2026-11-01',amount},
              {id:'previous',type:'income',date:'2026-10-01',amount:10000}];
            v146RenderHomeMonthly(v169HomeBalance('2026-11'));
            return document.querySelector('#v182HomeIncomeComparison .v182-comparison-change').textContent;
          });
        ''')
        self.assertIn('+<0,1%',result[0]);self.assertIn('+0,01',result[0])
        self.assertIn('−<0,1%',result[1]);self.assertIn('−0,01',result[1])

    def test_previous_month_edit_and_delete_refresh_comparison_without_changing_current_total(self):
        result=self.evaluate('''
          saveAll=async()=>true;openEdit('prior-income');document.getElementById('xAmount').value='2000';await saveEdit();
          const afterEdit=document.getElementById('v182HomeIncomeComparison').textContent,currentAfterEdit=readHomeMonthly().income;
          await deleteEntry('prior-income');return {afterEdit,currentAfterEdit,afterDelete:document.getElementById('v182HomeIncomeComparison').textContent,currentAfterDelete:readHomeMonthly().income};
        ''')
        self.assertIn('−82,5%',result['afterEdit']);self.assertIn('−1\u00a0649,65',result['afterEdit'])
        self.assertNotIn('%',result['afterDelete']);self.assertIn('0 ₽',result['afterDelete'])
        self.assertEqual(result['currentAfterEdit'],'350,35 ₽');self.assertEqual(result['currentAfterDelete'],'350,35 ₽')


if __name__=='__main__':unittest.main(verbosity=2)
