"""Monthly expense overview and overlapping cuts use fictional data, with no network."""
import json
import re
import unittest

import test_local_data_safety as harness


class WifeDashboard(unittest.TestCase):
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
        self.page.evaluate("""() => {
          session=null;stopCloudSync();state=blankState();localStorage.clear();
          today=()=> '2026-10-26';month=()=> '2026-10';
          loanScheduleData=()=>[{n:1,payDate:'2099-12-01',periodEnd:'2099-12-01',payment:1,interest:0,body:1,balance:0}];
          weatherCache.data={temperature_2m:10,weather_code:0};weatherCache.at=Date.now();
          const row=(id,amount,category,beneficiary,extra={})=>({id,type:'expense',
            date:'2026-10-15',amount,category,beneficiary,who:'Сохранённый автор',
            store:'Учебный магазин',comment:'Вымышленная покупка',unknown:{keep:[id,null,true]},...extra});
          state.entries=[row('fictional-food',10.10,'Продукты','Общее'),
            row('fictional-service',1000.25,'Подписки','Сергей',{store:'Учебный сервис'}),
            row('fictional-gift',7.50,'Подарки','Виктория'),
            row('fictional-car',20.20,'Авто и транспорт','Автомобиль',{subcategory:'Бензин'}),
            row('fictional-loan',30.30,'Кредит','Кредиты и рассрочки'),
            row('fictional-unknown',0.10,'Прочее','',{who:''}),row('fictional-sport',0.20,'Спорт и здоровье','Виктория'),
            row('fictional-earlier',500,'Подписки','Сергей',{date:'2026-09-18',store:'Прошлый учебный сервис'}),
            row('fictional-transfer',5000,'Продукты','Общее',{type:'transfer'}),
            row('fictional-income',9000,'Зарплата','Сергей',{type:'income'})];
          showApp();renderAll();go('home');homeMonth.value='2026-10';renderHome();
        }""")

    def test_month_and_both_scales_always_precede_other_overview_blocks(self):
        self.prepare();before=self.snapshot()
        for full in [False, True]:
            with self.subTest(full=full):
                self.page.evaluate('(full)=>v97SetHomeOverview(!full,false)',full)
                result=self.page.evaluate("""() => {
                  const rect=id=>document.getElementById(id).getBoundingClientRect();
                  const scale=rect('v99HomeSpending'),month=rect('homeMonth'),total=rect('v99HomeExpenseTotal');
                  return {visible:['v99HomeSpending','categoryLegend','familyBars'].every(id=>rect(id).height>0),
                    scaleTop:scale.top,monthTop:month.top,totalTop:total.top,
                    below:['v99HomeDirections','v99HomeSlices','v96MonthlyReview'].map(id=>rect(id).top),
                    heroTop:document.querySelector('#home>.hero').getBoundingClientRect().top};
                }""")
                self.assertTrue(result['visible'])
                self.assertLess(result['monthTop'],result['totalTop'])
                self.assertLess(result['scaleTop'],result['heroTop'])
                self.assertTrue(all(top>result['scaleTop'] for top in result['below']))
        self.assertEqual(self.snapshot(),before)

    def test_exact_monthly_total_excludes_income_transfers_and_plans_and_reconciles_cuts(self):
        self.prepare();before=self.snapshot()
        result=self.page.evaluate("""() => ({
          total:sum(expenses(homeMonth())),groups:v99DashboardTotals(expenses(homeMonth()),expenseEntryGroup),
          targets:v99DashboardTotals(expenses(homeMonth()),v94ExpenseBucket),
          services:v99DirectionEntryRows('subscriptions',expenses(homeMonth())).map(e=>e.id),
          car:v99DirectionEntryRows('car',expenses(homeMonth())).map(e=>e.id),
          loans:v99DirectionEntryRows('loans',expenses(homeMonth())).map(e=>e.id)})""")
        self.assertEqual(result['total'],1068.65)
        self.assertAlmostEqual(sum(v for _,v in result['groups']),1068.65)
        self.assertAlmostEqual(sum(v for _,v in result['targets']),1068.65)
        self.assertEqual(result['services'],['fictional-service'])
        self.assertEqual(result['car'],['fictional-car'])
        self.assertEqual(result['loans'],['fictional-loan'])
        self.assertIn('1 068,65',self.page.locator('#v99HomeExpenseTotal').inner_text().replace('\xa0',' '))
        self.assertIn('1 068,65',self.page.locator('.v862-total-note').inner_text().replace('\xa0',' '))
        self.assertEqual(self.snapshot(),before)

    def test_personal_subscription_and_gift_overlap_without_changing_total_or_history(self):
        self.prepare();before=self.snapshot()
        self.assertIn('1 000,25',self.page.locator('#v99SubscriptionTotal').inner_text().replace('\xa0',' '))
        self.assertIn('7,50',self.page.locator('#v99GiftTotal').inner_text())
        for direction,expected in [('person:Сергей','fictional-service'),('subscriptions','fictional-service'),
                                   ('person:Виктория','fictional-gift'),('gifts','fictional-gift')]:
            self.page.evaluate('(id)=>v84Drill("direction",id,"home")',direction)
            ids=self.page.locator('#v84DrillEntries button[data-record-action="drill-entry-edit"]').evaluate_all(
                'nodes=>nodes.map(n=>JSON.parse(n.dataset.recordArgs)[0])')
            self.assertIn(expected,ids)
            self.page.evaluate('v84CloseDrill()')
        self.assertIn('разные срезы',self.page.locator('.v99-overlap-note').inner_text())
        self.assertEqual(self.snapshot(),before)

    def test_service_summary_opens_exact_rows_and_edit_returns_to_same_month_and_service(self):
        self.prepare()
        self.page.locator('#v99SubscriptionList button').filter(has_text='Учебный сервис').click()
        self.assertEqual(self.page.locator('#v84DrillTitle').inner_text(),'Подписки и онлайн-сервисы')
        self.assertEqual(self.page.locator('#v84DrillEntries .v85-drill-entry').count(),1)
        self.page.locator('#v84DrillEntries').get_by_role('button',name=re.compile('^Изменить операцию:')).click()
        self.assertEqual(self.page.evaluate('editId'),'fictional-service')
        before=json.loads(self.snapshot()['state'])
        self.page.locator('#xAmount').fill('999,99')
        self.page.locator('#editModal').get_by_role('button',name='Сохранить',exact=True).click()
        self.page.wait_for_function('document.getElementById("v84DrillModal").classList.contains("open")')
        after=json.loads(self.snapshot()['state'])
        changed=[entry['id'] for entry,old in zip(after['entries'],before['entries']) if entry!=old]
        self.assertEqual(changed,['fictional-service'])
        self.assertEqual(after['entries'][1]['unknown'],before['entries'][1]['unknown'])
        self.assertEqual(self.page.locator('#homeMonth').input_value(),'2026-10')
        self.assertEqual(self.page.evaluate('v96DrillContext.sub'),'Учебный сервис')
        self.assertIn('999,99',self.page.locator('#v99SubscriptionTotal').inner_text().replace('\xa0',' '))
        self.assertIn('999,99',self.page.locator('#v96DrillTotal').inner_text())

    def test_month_change_updates_both_scales_and_service_list_without_touching_rows(self):
        self.prepare();before=self.snapshot()
        self.page.locator('#homeMonth').select_option('2026-09')
        self.assertIn('500,00',self.page.locator('#v99HomeExpenseTotal').inner_text().replace('\xa0',' '))
        self.assertIn('500,00',self.page.locator('#v99SubscriptionTotal').inner_text().replace('\xa0',' '))
        self.assertIn('Прошлый учебный сервис',self.page.locator('#v99SubscriptionList').inner_text())
        self.assertNotIn('1 000,25',self.page.locator('#categoryLegend').inner_text())
        self.page.locator('#v99HomeDirectionTiles [data-v99-direction="subscriptions"]').click()
        self.assertIn('Прошлый учебный сервис',self.page.locator('#v84DrillEntries').inner_text())
        self.assertEqual(self.page.locator('#v96DrillCount').inner_text(),'1')
        self.assertEqual(self.snapshot(),before)

    def test_primary_scales_tiles_and_money_fit_six_widths_and_200_percent_text(self):
        self.prepare();before=self.snapshot()
        for width in [320,390,768,1280,1536,1920]:
            for zoom in [1,2]:
                with self.subTest(width=width,zoom=zoom):
                    self.page.set_viewport_size({'width':width,'height':900})
                    self.page.evaluate('(z)=>document.documentElement.style.zoom=String(z)',zoom)
                    result=self.page.evaluate("""()=>({width:innerWidth,doc:document.documentElement.scrollWidth,
                      bad:[...document.querySelectorAll('#v99HomeSpending,#v99HomeDirections,#v99HomeSlices,#v99HomeSpending button,.v99-direction-tile,.v99-slice-row')]
                      .map(n=>{const r=n.getBoundingClientRect();return {id:n.id,cls:n.className,left:r.left,right:r.right,sw:n.scrollWidth,cw:n.clientWidth}})
                      .filter(r=>r.left<-.5||r.right>innerWidth+.5||r.sw>r.cw+2)})""")
                    self.assertLessEqual(result['doc'],width+1,result)
                    self.assertEqual(result['bad'],[],result)
        self.assertEqual(self.snapshot(),before)


if __name__=='__main__':unittest.main()
