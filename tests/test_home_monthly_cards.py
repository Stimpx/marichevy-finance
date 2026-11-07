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

    def test_monthly_card_rendering_preserves_existing_available_amount_and_ledger(self):
        result=self.evaluate('''const before={available:document.getElementById('v121HomeAvailable').textContent,title:document.getElementById('v121HomeAvailableTitle').textContent,ledger:JSON.stringify(state.entries),settings:JSON.stringify(state.settings)};v146RenderHomeMonthly(v111MonthBalance(homeMonth()));v146RenderHomeMonthly(v111MonthBalance(homeMonth()));const after={available:document.getElementById('v121HomeAvailable').textContent,title:document.getElementById('v121HomeAvailableTitle').textContent,ledger:JSON.stringify(state.entries),settings:JSON.stringify(state.settings)};return {same:JSON.stringify(before)===JSON.stringify(after),available:before.available.replaceAll('\\u00a0',' '),cards:readHomeMonthly()};''')
        self.assertTrue(result['same']);self.assertEqual(result['available'],'1 150,35 ₽')
        self.assertEqual(result['cards']['income'],'350,35 ₽');self.assertEqual(result['cards']['expense'],'100,00 ₽')


if __name__=='__main__':unittest.main(verbosity=2)
