"""Offline analytics period regressions with synthetic operations.

Run: python -m unittest discover -s tests -p test_analytics_periods.py
Requires Playwright and Chromium; no real account or external request is used.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

SOURCE=Path(os.environ.get('ANALYTICS_TEST_HTML',str(Path(__file__).resolve().parents[1]/'index.html')))
HTML=SOURCE.read_text()
BASE='http://127.0.0.1:9893/'

class AnalyticsPeriods(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=sync_playwright().start()
        executable=os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser=cls.p.chromium.launch(headless=True,**({'executable_path':executable} if executable else {}))
    @classmethod
    def tearDownClass(cls):
        cls.browser.close();cls.p.stop()
    def setUp(self):
        self.context=self.browser.new_context(timezone_id='Europe/Moscow',service_workers='block',viewport={'width':1280,'height':1000})
        self.context.route('**/*',lambda route:route.fulfill(status=200,content_type='text/html',body=HTML) if route.request.url==BASE else route.abort())
        self.page=self.context.new_page();self.errors=[];self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.goto(BASE,wait_until='domcontentloaded');self.page.wait_for_function("typeof v130AnalyticsExpenses==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;localStorage.clear();state=blankState();
          const stamp='2026-11-02T12:00:00.000Z',expense=(id,date,amount,category,beneficiary,subcategory='')=>({id,date,amount,type:'expense',category,beneficiary,subcategory,who:'Общее',store:'Тестовый магазин',comment:'Только вымышленные данные',pay:'Карта',created_at:stamp,updated_at:stamp});
          state.entries=[expense('oct-food','2026-10-10',100.10,'Продукты','Сергей'),expense('nov-food','2026-11-02',50.20,'Продукты','Сергей'),expense('oct-parking','2026-10-11',200,'Авто и транспорт','Автомобиль','Парковка'),expense('nov-fuel','2026-11-02',800,'Бензин','Автомобиль'),expense('oct-pet','2026-10-12',60,'Животные','Макс'),expense('nov-child','2026-11-02',90,'Дети','Алиса','Школа'),{id:'income',date:'2026-11-02',amount:10000,type:'income',category:'Зарплата',who:'Сергей'},{id:'transfer',date:'2026-10-10',amount:5000,type:'transfer',from:'Карта',to:'Накопления'},{id:'debt-transfer',date:'2026-11-02',amount:1000,type:'transfer',debtRepayment:true,category:'Кредит'}];
          showApp();go('analytics');document.getElementById('analyticsMonth').value='2026-11';renderAnalytics();
          window.setAnalyticsScope=scope=>{const node=document.getElementById('analyticsScope');node.value=scope;node.dispatchEvent(new Event('change',{bubbles:true}));};
          window.syntheticLedger=JSON.stringify(state.entries);
        }''')
    def tearDown(self):
        errors=self.errors;self.context.close();self.assertEqual(errors,[])
    def evaluate(self,code):return self.page.evaluate('async () => {'+code+'}')
    def test_monthly_and_all_history_totals_exclude_income_and_transfers(self):
        r=self.evaluate('''const monthly={sum:sum(v130AnalyticsExpenses()),ids:v130AnalyticsExpenses().map(e=>e.id).sort(),allCard:document.getElementById('v130AnalyticsAllTotal').textContent};setAnalyticsScope('all');return {monthly,all:{sum:sum(v130AnalyticsExpenses()),ids:v130AnalyticsExpenses().map(e=>e.id).sort(),donut:document.getElementById('peopleDonutTotal').textContent,headline:document.getElementById('v130AnalyticsPeriodTotal').textContent,hiddenMonth:document.getElementById('v130AnalyticsMonthField').hidden},unchanged:JSON.stringify(state.entries)===syntheticLedger};''')
        self.assertAlmostEqual(r['monthly']['sum'],940.2);self.assertEqual(r['monthly']['ids'],['nov-child','nov-food','nov-fuel']);self.assertEqual(r['monthly']['allCard'],'1\u00a0300,30 ₽')
        self.assertAlmostEqual(r['all']['sum'],1300.3);self.assertEqual(len(r['all']['ids']),6);self.assertEqual(r['all']['donut'],'1\u00a0300,30 ₽');self.assertEqual(r['all']['headline'],'1\u00a0300,30 ₽');self.assertTrue(r['all']['hiddenMonth']);self.assertTrue(r['unchanged'])
    def test_switch_back_to_another_month_restores_monthly_values(self):
        r=self.evaluate('''setAnalyticsScope('all');setAnalyticsScope('month');document.getElementById('analyticsMonth').value='2026-10';document.getElementById('analyticsMonth').dispatchEvent(new Event('change',{bubbles:true}));return {sum:sum(v130AnalyticsExpenses()),period:document.getElementById('v130AnalyticsPeriodLabel').textContent,hidden:document.getElementById('v130AnalyticsMonthField').hidden,home:homeMonth(),planning:v84ThisMonth()};''')
        self.assertAlmostEqual(r['sum'],360.1);self.assertIn('октябрь',r['period']);self.assertFalse(r['hidden']);self.assertEqual(r['home'],'2026-10');self.assertEqual(r['planning'],'2026-10')
    def test_all_scope_preserves_home_planning_and_obligations(self):
        r=self.evaluate('''const before={home:homeMonth(),planning:v84ThisMonth(),ob:v78Obligations('2026-11'),forecast:v86Forecast()};setAnalyticsScope('all');const after={home:homeMonth(),planning:v84ThisMonth(),ob:v78Obligations('2026-11'),forecast:v86Forecast()};return {same:cloudJSONEqual(before,after),home:homeMonth(),planning:v84ThisMonth()};''')
        self.assertTrue(r['same']);self.assertEqual(r['home'],'2026-11');self.assertEqual(r['planning'],'2026-11')
    def test_people_category_and_life_drills_share_all_period(self):
        r=self.evaluate('''setAnalyticsScope('all');v81SetFocus('auto');const autoSummary=document.getElementById('v81LifeSummary').textContent;v84Drill('person','Автомобиль','analytics');const auto={scope:v96DrillContext.scope,total:document.getElementById('v96DrillTotal').textContent,count:document.getElementById('v96DrillCount').textContent,dates:[...document.querySelectorAll('#v84DrillEntries time')].map(x=>x.textContent)};v84CloseDrill();const foodGroup=expenseEntryGroup(state.entries.find(e=>e.id==='oct-food'));v84Drill('group',foodGroup,'analytics');return {autoSummary,auto,food:{total:document.getElementById('v96DrillTotal').textContent,count:document.getElementById('v96DrillCount').textContent,period:document.getElementById('v84DrillPeriod').textContent}};''')
        self.assertIn('1\u00a0000',r['autoSummary']);self.assertIn('За всё время',r['autoSummary']);self.assertEqual(r['auto']['scope'],'all');self.assertEqual(r['auto']['total'],'1\u00a0000,00 ₽');self.assertEqual(r['auto']['count'],'2');self.assertEqual(set(r['auto']['dates']),{'11.10.2026','02.11.2026'});self.assertEqual(r['food']['total'],'150,30 ₽');self.assertEqual(r['food']['count'],'2');self.assertIn('За всё время',r['food']['period'])
    def test_browser_back_restores_all_scope(self):
        self.evaluate("setAnalyticsScope('all');")
        self.page.wait_for_timeout(60)
        self.evaluate("go('history');")
        self.page.go_back()
        self.page.wait_for_function("document.getElementById('analytics').classList.contains('active')")
        r=self.evaluate("return {scope:document.getElementById('analyticsScope').value,sum:sum(v130AnalyticsExpenses()),month:document.getElementById('analyticsMonth').value};")
        self.assertEqual(r['scope'],'all');self.assertAlmostEqual(r['sum'],1300.3);self.assertEqual(r['month'],'2026-11')
    def test_edit_and_delete_from_all_history_drill_keep_scope_and_totals(self):
        r=self.evaluate('''setAnalyticsScope('all');v84Drill('person','Сергей','analytics');v96EditFromDrill('nov-food');document.getElementById('xAmount').value='60.20';await saveEdit();const edited={scope:v96DrillContext.scope,total:document.getElementById('v96DrillTotal').textContent,count:document.getElementById('v96DrillCount').textContent,amount:state.entries.find(e=>e.id==='nov-food').amount};window.confirm=()=>true;v96DeleteFromDrill('oct-food');await new Promise(requestAnimationFrame);return {edited,deleted:{scope:v96DrillContext.scope,total:document.getElementById('v96DrillTotal').textContent,count:document.getElementById('v96DrillCount').textContent,scopeSelect:document.getElementById('analyticsScope').value,allTotal:sum(v130AnalyticsExpenses())}};''')
        self.assertEqual(r['edited'],{'scope':'all','total':'160,30 ₽','count':'2','amount':60.2});self.assertEqual(r['deleted']['scope'],'all');self.assertEqual(r['deleted']['total'],'60,20 ₽');self.assertEqual(r['deleted']['count'],'1');self.assertEqual(r['deleted']['scopeSelect'],'all');self.assertAlmostEqual(r['deleted']['allTotal'],1210.2)
    def test_category_review_returns_to_analytics_scope(self):
        r=self.evaluate('''setAnalyticsScope('all');v98OpenCategoryReview();const reviewAll=v98CategoryReviewState.allTime;v98BackToAnalytics();return {reviewAll,scope:document.getElementById('analyticsScope').value,active:document.getElementById('analytics').classList.contains('active'),sum:sum(v130AnalyticsExpenses())};''')
        self.assertTrue(r['reviewAll']);self.assertEqual(r['scope'],'all');self.assertTrue(r['active']);self.assertAlmostEqual(r['sum'],1300.3)
    def test_empty_all_history_has_zeroes_and_preserves_operations(self):
        r=self.evaluate('''state.entries=state.entries.filter(e=>e.type!=='expense');const before=JSON.stringify(state.entries);setAnalyticsScope('all');return {sum:sum(v130AnalyticsExpenses()),total:document.getElementById('v130AnalyticsPeriodTotal').textContent,empty:document.getElementById('aPeopleChart').textContent,unchanged:JSON.stringify(state.entries)===before};''')
        self.assertEqual(r['sum'],0);self.assertEqual(r['total'],'0,00 ₽');self.assertNotIn('NaN',r['empty']);self.assertTrue(r['unchanged'])

if __name__=='__main__':unittest.main(verbosity=2)
