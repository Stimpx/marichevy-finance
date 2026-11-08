"""Home top expense categories on isolated synthetic records.

Run: python -m unittest discover -s tests -p test_home_top_categories.py
Playwright/Chromium are required; every external request is blocked.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

HTML=(Path(__file__).resolve().parents[1]/'index.html').read_text()
BASE='http://127.0.0.1:9887/'


class HomeTopCategories(unittest.TestCase):
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
        self.page.wait_for_function("typeof v147RenderHomeTopCategories==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;localStorage.clear();state=blankState();
          today=()=> '2026-11-08';month=()=> '2026-11';
          window.topTestEntry=(id,category,amount,fields={})=>({id,type:'expense',date:'2026-11-04',amount,category,subcategory:'',beneficiary:'Общее',who:'Общее',store:'Тестовый магазин',comment:'Синтетическая запись',pay:'Карта',created_at:'2026-11-08T12:00:00.000Z',updated_at:'2026-11-08T12:00:00.000Z',...fields});
          state.entries=[topTestEntry('school','Школа и занятия',500.25),topTestEntry('home','Дом',400.10),topTestEntry('food-a','Продукты',300.10),topTestEntry('food-b','Продукты',.20),topTestEntry('snacks','Вкусняшки',250.20),topTestEntry('sport','Спорт',150.10),topTestEntry('fitness','Фитнес',50.20),topTestEntry('clothes','Одежда',100.50),topTestEntry('prior','Одежда',9999.99,{date:'2026-10-04'}),topTestEntry('prior-child','Дети',1.01,{date:'2026-10-05'}),topTestEntry('prior-income','Доход',20000,{type:'income',date:'2026-10-01',beneficiary:'',who:'Сергей'}),topTestEntry('future','Кредит',1000000,{date:'2026-12-01'}),topTestEntry('income','Доход',10000,{type:'income',beneficiary:'',who:'Алиса'}),topTestEntry('transfer','Движение денег',90000,{type:'transfer'}),topTestEntry('cash','Наличные',80000,{type:'cash'}),topTestEntry('adjustment','Сверка остатка',70000,{type:'transfer',balanceAdjustment:true,adjustmentDirection:1})];
          state.intelligence.recurring.push({id:'only-plan',name:'Запланированное',amount:500000,day:28,category:'Дом'});
          showApp();go('home');document.getElementById('homeMonth').value='2026-11';renderHome();
          window.originalTopLedger=JSON.stringify(state.entries);window.originalTopSettings=JSON.stringify(state.settings);
          window.readHomeTop=()=>[...document.querySelectorAll('#v147HomeTopList .v147-top-row')].map(row=>({name:row.querySelector('.v147-top-name').textContent,amount:row.querySelector('.v147-top-value').textContent.replaceAll('\\u00a0',' '),width:parseFloat(row.querySelector('.v147-top-bar>span').style.width)}));
        }''')

    def tearDown(self):
        self.context.close();self.assertEqual(self.errors,[])

    def evaluate(self,code):
        return self.page.evaluate('async () => {'+code+'}')

    def test_top_five_use_monthly_expense_amounts_cents_and_canonical_aliases(self):
        result=self.evaluate('''return {rows:readHomeTop(),unchanged:JSON.stringify(state.entries)===originalTopLedger,settingsUnchanged:JSON.stringify(state.settings)===originalTopSettings};''')
        self.assertEqual([row['name'] for row in result['rows']],['Школа и занятия','Дом и быт','Продукты','Вкусняшки','Спорт и здоровье'])
        self.assertEqual([row['amount'] for row in result['rows']],['500,25 ₽','400,10 ₽','300,30 ₽','250,20 ₽','200,30 ₽'])
        self.assertEqual(result['rows'][0]['width'],100)
        self.assertAlmostEqual(result['rows'][2]['width'],300.30/500.25*100,delta=.1)
        self.assertTrue(result['unchanged']);self.assertTrue(result['settingsUnchanged'])

    def test_fewer_categories_and_empty_month_do_not_invent_zero_rows(self):
        result=self.evaluate('''state.entries=[topTestEntry('one','Продукты',12.25),topTestEntry('two','Дом',5.50),topTestEntry('not-expense','Доход',10000,{type:'income'})];renderHome();const fewer=readHomeTop();state.entries=[];renderHome();return {fewer,emptyRows:readHomeTop(),emptyText:document.getElementById('v147HomeTopList').textContent};''')
        self.assertEqual([row['name'] for row in result['fewer']],['Продукты','Дом и быт'])
        self.assertEqual([row['amount'] for row in result['fewer']],['12,25 ₽','5,50 ₽'])
        self.assertEqual(result['emptyRows'],[]);self.assertIn('Расходов за этот месяц пока нет',result['emptyText'])

    def test_actual_month_change_refreshes_ranking_without_mutating_records(self):
        result=self.evaluate('''const select=document.getElementById('homeMonth');select.value='2026-10';select.dispatchEvent(new Event('change',{bubbles:true}));return {rows:readHomeTop(),month:homeMonth(),unchanged:JSON.stringify(state.entries)===originalTopLedger};''')
        self.assertEqual(result['month'],'2026-10')
        self.assertEqual([row['name'] for row in result['rows']],['Одежда и обувь','Детские товары'])
        self.assertEqual([row['amount'] for row in result['rows']],['9 999,99 ₽','1,01 ₽']);self.assertTrue(result['unchanged'])
        self.page.evaluate("document.getElementById('analyticsScope').value='all';v130AnalyticsScopeChanged()")
        self.page.locator('#v147HomeAnalyticsButton').click()
        navigation=self.evaluate("return {active:document.getElementById('analytics').classList.contains('active'),scope:document.getElementById('analyticsScope').value,month:document.getElementById('analyticsMonth').value};")
        self.assertTrue(navigation['active']);self.assertEqual(navigation['scope'],'month');self.assertEqual(navigation['month'],'2026-10')

    def test_actual_add_edit_delete_refresh_ranking_and_keep_account_bank_consistent(self):
        result=self.evaluate('''const beforeAvailable=document.getElementById('v121HomeAvailable').textContent;openEntry('expense');document.getElementById('eAmount').value='300';v90Choose('Продукты');v133ChooseRecipient('eBeneficiary','Общее');await addEntry();const added=state.entries.at(-1),afterAdd=readHomeTop();openEdit(added.id);document.getElementById('xAmount').value='50';await saveEdit();const afterEdit=readHomeTop(),availableAfterEdit=document.getElementById('v121HomeAvailable').textContent,expectedAvailable='—';await deleteEntry(added.id);return {afterAdd,afterEdit,afterDelete:readHomeTop(),sameLedger:JSON.stringify(state.entries)===originalTopLedger,sameAvailable:document.getElementById('v121HomeAvailable').textContent===beforeAvailable,availableAfterEdit,expectedAvailable};''')
        self.assertEqual(result['afterAdd'][0]['name'],'Продукты');self.assertEqual(result['afterAdd'][0]['amount'],'600,30 ₽')
        food=next(row for row in result['afterEdit'] if row['name']=='Продукты');self.assertEqual(food['amount'],'350,30 ₽')
        self.assertEqual([row['name'] for row in result['afterDelete']],['Школа и занятия','Дом и быт','Продукты','Вкусняшки','Спорт и здоровье'])
        self.assertEqual(result['availableAfterEdit'],result['expectedAvailable']);self.assertTrue(result['sameLedger']);self.assertTrue(result['sameAvailable'])


if __name__=='__main__':unittest.main(verbosity=2)
