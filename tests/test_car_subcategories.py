"""Offline read-only car subcategory and drill-down regressions.

Run: python -m unittest discover -s tests -p test_car_subcategories.py
Requires Playwright and Chromium. All requests except this synthetic local page are blocked.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

SOURCE = Path(os.environ.get('FINANCE_TEST_HTML', Path(__file__).resolve().parents[1] / 'index.html'))
HTML = SOURCE.read_text()
BASE = 'http://127.0.0.1:9898/'

class CarSubcategories(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        executable = os.environ.get('CHROMIUM_EXECUTABLE') or shutil.which('chromium') or shutil.which('chromium-browser')
        cls.browser = cls.p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

    @classmethod
    def tearDownClass(cls):
        cls.browser.close(); cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={'width':1280, 'height':1000}, timezone_id='Europe/Moscow', service_workers='block')
        self.context.route('**/*', lambda r: r.fulfill(status=200, content_type='text/html', body=HTML) if r.request.url == BASE else r.abort())
        self.page = self.context.new_page(); self.errors = []
        self.page.on('pageerror', lambda e:self.errors.append(str(e)))
        self.page.goto(BASE, wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v131CarCommentDetail==='function'")
        self.page.evaluate('''() => {
          session=null;localStorage.clear();state=blankState();localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;
          today=()=> '2026-11-03';month=()=> '2026-11';
          const mk=(id,amount,fields={})=>({id,type:'expense',date:'2026-10-30',amount,category:'Авто и транспорт',subcategory:'',who:'Общее',beneficiary:'Общее',store:'',comment:'',created_at:'2026-10-30T12:00:00.000Z',updated_at:'2026-10-30T12:00:00.000Z',...fields});
          state.entries=[
            mk('synthetic-gas',3048,{subcategory:'Бензин',store:'Тестовая АЗС'}),
            mk('synthetic-parking-note',200,{comment:'  ПАРКОВКА  ',beneficiary:'Автомобиль'}),
            mk('synthetic-parking',8300,{subcategory:'Парковка'}),
            mk('synthetic-unknown',2500,{comment:'Бензин и парковка',store:'Тестовая АЗС'}),
            mk('synthetic-explicit-other',400,{subcategory:'Другое',comment:'бензин'}),
            mk('synthetic-legacy-gas',150,{category:'Бензин'}),
            mk('synthetic-explicit-unknown',300,{subcategory:'Кузов',comment:'парковка'}),
            mk('synthetic-november',1000,{subcategory:'Бензин',date:'2026-11-01'}),
            mk('synthetic-taxi',500,{subcategory:'Такси'}),
            mk('synthetic-food',700,{category:'Продукты'}),
            mk('synthetic-income',90000,{type:'income',category:'Зарплата'}),
            mk('synthetic-transfer',10000,{type:'transfer',category:'Перевод'})
          ];
          showApp();go('analytics');const m=document.getElementById('analyticsMonth');
          if(![...m.options].some(o=>o.value==='2026-10'))m.add(new Option('октябрь 2026','2026-10'));
          m.value='2026-10';const scope=document.getElementById('analyticsScope');if(scope)scope.value='month';renderAnalytics();v84RenderAll();
          window.originalCarEntries=JSON.stringify(state.entries);
        }''')

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.context.close()

    def evaluate(self, code):
        return self.page.evaluate('() => {'+code+'}')

    def open_drill(self, mode='person', key='Автомобиль'):
        self.page.evaluate('([mode,key])=>v84Drill(mode,key,\'analytics\')', [mode,key])

    def visible(self):
        return self.evaluate('''return {total:document.getElementById('v96DrillTotal').textContent.replace(/\\u00a0/g,' '),count:Number(document.getElementById('v96DrillCount').textContent),chips:[...document.querySelectorAll('#v84DrillBody [data-v84-sub]')].map(b=>b.dataset.v84Sub),rows:document.querySelectorAll('#v84DrillEntries .v84-drill-entry').length,period:document.getElementById('v84DrillPeriod').textContent};''')

    def test_exact_saved_details_and_comments_classify_without_mutation(self):
        result=self.evaluate('''return {details:Object.fromEntries(state.entries.map(e=>[e.id,carCategory(e)])),unchanged:JSON.stringify(state.entries)===originalCarEntries};''')
        self.assertTrue(result['unchanged'])
        self.assertEqual(result['details']['synthetic-gas'],'Бензин')
        self.assertEqual(result['details']['synthetic-parking-note'],'Парковка')
        self.assertEqual(result['details']['synthetic-legacy-gas'],'Бензин')
        for key in ['synthetic-unknown','synthetic-explicit-other','synthetic-explicit-unknown']:
            self.assertEqual(result['details'][key],'Без уточнения')
        self.assertEqual(result['details']['synthetic-taxi'],'')
        self.assertEqual(result['details']['synthetic-food'],'')

    def test_exclusive_car_report_has_distinct_totals_and_filters(self):
        self.open_drill();data=self.visible()
        self.assertEqual((data['total'],data['count'],data['rows']),('14 898,00 ₽',7,7))
        self.assertEqual(set(data['chips']),{'','Бензин','Парковка','Без уточнения'})
        self.assertIn('По подкатегориям',self.page.locator('#v84DrillBody').inner_text())
        self.page.locator('#v84DrillBody [data-v84-sub="Парковка"]').click()
        self.assertEqual((self.visible()['total'],self.visible()['count'],self.visible()['rows']),('8 500,00 ₽',2,2))
        self.page.locator('#v84DrillBody [data-v84-sub="Бензин"]').click()
        self.assertEqual((self.visible()['total'],self.visible()['count']),('3 198,00 ₽',2))
        self.page.locator('#v84DrillBody [data-v84-sub="Без уточнения"]').click()
        self.assertEqual((self.visible()['total'],self.visible()['count']),('3 200,00 ₽',3))
        self.assertTrue(self.evaluate('return JSON.stringify(state.entries)===originalCarEntries;'))

    def test_car_direction_uses_the_same_partition_without_double_counting(self):
        self.open_drill('direction','car');data=self.visible()
        self.assertEqual((data['total'],data['count']),('14 898,00 ₽',7))
        self.assertEqual(set(data['chips']),{'','Бензин','Парковка','Без уточнения'})
        values=self.evaluate('''const rows=v130AnalyticsExpenses().filter(e=>carCategory(e));return {sum:sum(rows),groups:v99DashboardTotals(rows,e=>carCategory(e)),count:rows.length};''')
        self.assertEqual(sum(x[1] for x in values['groups']),values['sum'])
        self.assertEqual(values['count'],7)

    def test_all_time_car_totals_include_months_and_keep_subcategory_filter(self):
        self.page.evaluate("document.getElementById('analyticsScope').value='all';renderAnalytics();v84RenderAll();")
        self.open_drill();data=self.visible()
        self.assertEqual((data['total'],data['count']),('15 898,00 ₽',8))
        self.assertIn('За всё время',data['period'])
        self.page.locator('#v84DrillBody [data-v84-sub="Бензин"]').click()
        self.assertEqual((self.visible()['total'],self.visible()['count']),('4 198,00 ₽',3))
        context=self.evaluate("return {...v96DrillContext,scrollTop:0};")
        self.page.evaluate('(context)=>v96RestoreDrill(context)',context)
        self.assertEqual((self.visible()['total'],self.visible()['count']),('4 198,00 ₽',3))
        self.assertEqual(self.page.locator('#analyticsScope').input_value(),'all')
        self.assertTrue(self.evaluate('return JSON.stringify(state.entries)===originalCarEntries;'))

    def test_restoring_filtered_report_recomputes_current_operation_amount(self):
        self.open_drill();self.page.locator('#v84DrillBody [data-v84-sub="Парковка"]').click()
        self.page.evaluate("state.entries.find(e=>e.id==='synthetic-parking-note').amount=250;const context={...v96DrillContext};v96RestoreDrill(context,'Проверка',true);")
        self.assertEqual((self.visible()['total'],self.visible()['count']),('8 550,00 ₽',2))
        self.assertEqual(self.evaluate('return v96DrillContext.sub;'),'Парковка')

    def test_auto_tab_matches_drill_subcategories_for_legacy_and_comment_rows(self):
        self.page.evaluate("v81SetFocus('auto')")
        rows=self.evaluate('''return [...document.querySelectorAll('#v81LifeCategories .v81-life-row')].map(row=>[row.querySelector('span').textContent,row.querySelector('b').textContent.replace(/\\u00a0/g,' ')]);''')
        self.assertEqual(dict(rows),{'Парковка':'8 500 ₽','Бензин':'3 198 ₽','Без уточнения':'3 200 ₽'})
        self.page.evaluate("document.getElementById('analyticsScope').value='all';renderAnalytics();v81SetFocus('auto');")
        text=self.page.locator('#v81LifeCategories').inner_text().replace('\u00a0',' ')
        self.assertIn('4 198 ₽',text)

if __name__=='__main__':
    unittest.main(verbosity=2)
