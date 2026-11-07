"""Offline field-completion presentation checks on synthetic drafts.

Run: python -m unittest discover -s tests -p test_field_completion.py
Requires Playwright and Chromium; CHROMIUM_EXECUTABLE may override the browser.
All external requests are blocked; these tests never authenticate or save expenses.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

HTML=(Path(__file__).resolve().parents[1]/'index.html').read_text()
BASE='http://127.0.0.1:9897/'

class FieldCompletion(unittest.TestCase):
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
        self.page.goto(BASE,wait_until='domcontentloaded');self.page.wait_for_function("typeof v132RefreshFieldStates==='function'")
        self.page.evaluate('''() => {
          session=null;localStorage.clear();state=blankState();localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;window.confirm=()=>true;
          const stamp='2026-11-02T12:00:00.000Z';
          const expense={id:'synthetic-existing',type:'expense',date:today(),amount:123.45,category:'Продукты',subcategory:'',beneficiary:'Общее',who:'Общее',store:'Тестовый магазин',comment:'Тестовый комментарий',pay:'Карта',accountId:'synthetic-cash',created_at:stamp,updated_at:stamp};
          state.entries=[expense];state.intelligence.accounts=[{id:'synthetic-cash',name:'Тестовый счёт',amount:10000,snapshotDate:'2026-11-01',ledger:{version:1,enabled:true,startDate:'2026-11-01',openingBalance:10000,kind:'asset',includeInSpending:true}}];
          state.intelligence.favorites=[{...expense,id:'synthetic-favorite',name:'Тестовое избранное',amount:250,store:'Магазин избранного',comment:'Избранный черновик'}];
          showApp();go('today');clearEntry();window.originalEntries=JSON.stringify(state.entries);
        }''')
        self.page.wait_for_function("document.getElementById('eType').closest('.v107-select')?.querySelector('.v107-select-trigger')?.classList.contains('v132-filled')")
    def tearDown(self):
        self.assertTrue(self.page.evaluate('JSON.stringify(state.entries)===originalEntries'),'Highlighting must never rewrite financial records')
        self.context.close();self.assertEqual(self.errors,[])
    def evaluate(self,code):return self.page.evaluate('async () => {'+code+'}')
    def state_of(self,identifier):
        return self.page.locator('#'+identifier).evaluate("node=>({filled:node.classList.contains('v132-filled'),pending:node.classList.contains('v132-pending'),value:node.value})")
    def trigger(self,identifier):return self.page.locator('#'+identifier).locator('..').locator('.v107-select-trigger')
    def recipient(self,value,target='eBeneficiary'):return self.page.locator(f'button[data-v133-target="{target}"][data-v133-recipient="{value}"]')
    def open_details(self):
        if not self.page.locator('#v90Extra').evaluate('node=>node.open'):self.page.locator('#v90Extra > summary').click()
    def test_amount_and_text_follow_meaningful_input_and_clearing(self):
        self.assertFalse(self.state_of('eAmount')['filled'])
        for text in ['0','не сумма']:
            self.page.locator('#eAmount').fill(text)
            self.assertEqual((self.state_of('eAmount')['filled'],self.state_of('eAmount')['pending']),(False,True))
        self.page.locator('#eAmount').fill('1 250,50');self.assertTrue(self.state_of('eAmount')['filled'])
        self.page.locator('#eAmount').fill('');self.assertEqual((self.state_of('eAmount')['filled'],self.state_of('eAmount')['pending']),(False,False))
        self.assertFalse(self.page.locator('#v90Extra').evaluate('node=>node.open'))
        self.assertTrue(self.page.locator('#eStore').is_visible())
        self.page.locator('#eStore').fill('Тестовая парковка');self.assertTrue(self.state_of('eStore')['filled'])
        self.page.locator('#eStore').fill('   ');self.assertFalse(self.state_of('eStore')['filled'])
    def test_select_placeholders_real_choices_and_dynamic_account_proxy(self):
        self.assertFalse(self.state_of('eBeneficiary')['filled'])
        self.assertEqual(self.page.locator('#v133ExpenseRecipients [aria-pressed="true"]').count(),0)
        self.recipient('Автомобиль').focus();self.page.keyboard.press('Space')
        self.assertEqual(self.page.evaluate("document.activeElement?.dataset.v133Recipient"),'Автомобиль')
        self.assertTrue(self.state_of('eBeneficiary')['filled']);self.assertEqual(self.recipient('Автомобиль').get_attribute('aria-pressed'),'true')
        self.page.wait_for_function("getComputedStyle(document.querySelector('button[data-v133-recipient=\"Автомобиль\"]')).backgroundColor==='rgb(223, 243, 231)'")
        self.page.evaluate('clearEntry()')
        self.assertFalse(self.state_of('eBeneficiary')['filled']);self.assertEqual(self.page.locator('#v133ExpenseRecipients [aria-pressed="true"]').count(),0)
        self.open_details()
        self.assertFalse(self.state_of('eAccountId')['filled'])
        self.trigger('eAccountId').click();self.page.get_by_role('option',name='Тестовый счёт',exact=True).click()
        self.assertTrue(self.state_of('eAccountId')['filled']);self.assertIn('v132-filled',self.trigger('eAccountId').get_attribute('class'))
        self.page.evaluate("document.getElementById('eAccounts').remove();v119RefreshEntryAccounts(true)")
        self.page.wait_for_function("!document.getElementById('eAccountId').classList.contains('v132-filled')")
        self.assertNotIn('v132-filled',self.trigger('eAccountId').get_attribute('class'))
        self.page.locator('#eType').select_option('income',force=True)
        self.recipient('Виктория','eWho').click()
        self.assertEqual(self.page.locator('#eWho').input_value(),'Виктория')
        self.assertTrue(self.state_of('eWho')['filled']);self.assertEqual(self.recipient('Виктория','eWho').get_attribute('aria-pressed'),'true')
    def test_category_search_is_pending_until_actual_choice(self):
        self.page.locator('#v90Search').fill('парковка');self.assertEqual((self.state_of('v90Search')['filled'],self.state_of('v90Search')['pending']),(False,True))
        self.page.locator('#v90Quick [data-cat="Авто и транспорт"]').first.click()
        self.assertEqual(self.page.locator('#eCategory').input_value(),'Авто и транспорт')
        self.assertEqual(self.state_of('v90Search'),{'filled':True,'pending':False,'value':''})
        self.assertTrue(self.page.locator('#v92Selected').is_visible());self.assertIn('Авто и транспорт',self.page.locator('#v92Selected').inner_text())
        self.assertTrue(self.page.locator('#v81DetailField').is_visible());self.assertTrue(self.state_of('eSubcategory')['filled'])
        self.assertIn('v132-filled',self.trigger('eSubcategory').get_attribute('class'))
        self.trigger('eSubcategory').click();self.page.get_by_role('option',name='Без уточнения',exact=True).click()
        self.assertFalse(self.state_of('eSubcategory')['filled']);self.assertNotIn('v132-filled',self.trigger('eSubcategory').get_attribute('class'))
        self.page.locator('#v90Search').fill('корм');self.assertFalse(self.state_of('v90Search')['filled']);self.assertTrue(self.state_of('v90Search')['pending'])
        self.page.locator('#v90Search').fill('');self.assertFalse(self.state_of('v90Search')['filled']);self.assertFalse(self.state_of('v90Search')['pending'])
    def test_repeat_favorite_and_clear_refresh_programmatic_values(self):
        self.assertTrue(self.evaluate("return v97RepeatEntry('synthetic-existing');"))
        for identifier in ['eAmount','eStore','eComment','v90Search','eBeneficiary']:
            self.assertTrue(self.state_of(identifier)['filled'],identifier)
        self.assertEqual(self.recipient('Общее').get_attribute('aria-pressed'),'true')
        self.page.evaluate('clearEntry()')
        self.assertEqual(self.page.locator('#v133ExpenseRecipients [aria-pressed="true"]').count(),0)
        for identifier in ['eAmount','eStore','eComment','v90Search','eBeneficiary']:
            self.assertFalse(self.state_of(identifier)['filled'],identifier)
        self.assertTrue(self.evaluate("return v97OpenFavorite('synthetic-favorite');"))
        self.assertTrue(self.state_of('eAmount')['filled']);self.assertEqual(self.page.locator('#eAmount').input_value(),'250')
        self.assertTrue(self.state_of('eStore')['filled']);self.assertEqual(self.page.locator('#eStore').input_value(),'Магазин избранного')
        self.page.evaluate('clearEntry()');self.assertFalse(self.state_of('eAmount')['filled'])
    def test_edit_existing_fields_and_date_icon_keep_completion(self):
        self.page.evaluate("openEdit('synthetic-existing')")
        self.page.wait_for_function("document.getElementById('xAmount').classList.contains('v132-filled')")
        for identifier in ['xAmount','xStore','xComment','xDate','xCat','xBeneficiary','xAccountId']:
            self.assertTrue(self.state_of(identifier)['filled'],identifier)
        self.assertIn('v132-filled',self.trigger('xAccountId').get_attribute('class'))
        self.assertNotEqual(self.page.locator('#xDate').evaluate('node=>getComputedStyle(node).backgroundImage'),'none')
        self.page.locator('#xStore').fill('');self.assertFalse(self.state_of('xStore')['filled'])
        self.page.locator('#xType').select_option('transfer',force=True)
        self.page.wait_for_function("document.getElementById('xFromAccountId').closest('.v107-select')?.querySelector('.v107-select-trigger')")
        self.assertFalse(self.state_of('xFromAccountId')['filled'])
        self.page.locator('#xFromAccountId').select_option('synthetic-cash',force=True)
        self.assertTrue(self.state_of('xFromAccountId')['filled']);self.assertIn('v132-filled',self.trigger('xFromAccountId').get_attribute('class'))
    def test_errors_focus_and_repeated_refresh_do_not_hide_or_churn(self):
        self.page.locator('#eAmount').fill('200');self.assertTrue(self.state_of('eAmount')['filled'])
        self.page.evaluate("v114EntryError('amount','Тестовая ошибка суммы')")
        self.page.wait_for_function("getComputedStyle(document.getElementById('eAmount')).backgroundColor==='rgb(255, 244, 244)' && getComputedStyle(document.getElementById('eAmount')).borderTopColor==='rgb(193, 81, 99)'")
        colors=self.page.locator('#eAmount').evaluate('node=>({background:getComputedStyle(node).backgroundColor,border:getComputedStyle(node).borderTopColor})')
        self.assertEqual(colors,{'background':'rgb(255, 244, 244)','border':'rgb(193, 81, 99)'})
        self.page.locator('#eAmount').fill('201');self.assertIsNone(self.page.locator('#eAmount').get_attribute('aria-invalid'))
        self.page.wait_for_function("getComputedStyle(document.getElementById('eAmount')).backgroundColor==='rgb(237, 248, 241)'")
        self.assertEqual(self.page.locator('#eAmount').evaluate('node=>getComputedStyle(node).backgroundColor'),'rgb(237, 248, 241)')
        self.page.keyboard.press('Tab');self.trigger('eType').focus()
        outline=self.trigger('eType').evaluate('node=>({style:getComputedStyle(node).outlineStyle,width:parseFloat(getComputedStyle(node).outlineWidth)})')
        self.assertNotEqual(outline['style'],'none');self.assertGreater(outline['width'],0)
        r=self.evaluate('''await new Promise(requestAnimationFrame);let count=0;const observer=new MutationObserver(records=>{count+=records.length});observer.observe(document.querySelector('#today .v91-form'),{subtree:true,attributes:true,attributeFilter:['class','data-v132-state']});v132RefreshFieldStates();v132RefreshFieldStates();v110RefreshPickers();await new Promise(requestAnimationFrame);await new Promise(requestAnimationFrame);observer.disconnect();return {count,icon:getComputedStyle(document.getElementById('eDate')).backgroundImage};''')
        self.assertEqual(r['count'],0);self.assertNotEqual(r['icon'],'none')

if __name__=='__main__':unittest.main(verbosity=2)
