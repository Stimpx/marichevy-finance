"""Offline checks for the compact entry form using synthetic drafts and operations.

Run: python -m unittest discover -s tests -p test_entry_layout.py
Requires Playwright and Chromium; CHROMIUM_EXECUTABLE may select a browser.
The document is served by route.fulfill; no authenticated session or network is used.
"""
from pathlib import Path
import os, shutil, unittest
from playwright.sync_api import sync_playwright

HTML=(Path(__file__).resolve().parents[1]/'index.html').read_text()
BASE='http://127.0.0.1:9898/'


class EntryLayout(unittest.TestCase):
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
        self.page=self.context.new_page();self.errors=[]
        self.page.on('pageerror',lambda error:self.errors.append(str(error)))
        self.page.goto(BASE,wait_until='domcontentloaded')
        self.page.wait_for_function("typeof v133RenderRecipients==='function'")
        self.page.evaluate('''() => {
          session=null;localRecoveryBlocked=false;window.__FINANCE_BRIDGE__=null;window.confirm=()=>true;
          localStorage.clear();state=blankState();
          const stamp=today()+'T12:00:00.000Z';
          const expense={id:'synthetic-existing',type:'expense',date:today(),amount:123.45,category:'Продукты',subcategory:'',beneficiary:'Общее',who:'Общее',store:'Тестовый магазин',comment:'Вымышленная покупка',pay:'Карта',created_at:stamp,updated_at:stamp};
          state.entries=[expense];
          state.intelligence.favorites=[{...expense,id:'synthetic-favorite',name:'Тестовое избранное',amount:250,store:'Магазин избранного',comment:'Избранный черновик'}];
          showApp();go('today');clearEntry();window.originalEntryJSON=JSON.stringify(state.entries);
        }''')
        self.page.wait_for_function("document.querySelector('#v133ExpenseRecipients button[data-v133-recipient]')")

    def tearDown(self):
        errors=self.errors;self.context.close();self.assertEqual(errors,[])

    def evaluate(self,code):
        return self.page.evaluate('async () => {'+code+'}')

    def chip(self,value,target='eBeneficiary'):
        return self.page.locator('button[data-v133-target="'+target+'"][data-v133-recipient="'+value+'"]')

    def test_desktop_main_order_keeps_date_visible_and_recipient_next_to_amount(self):
        r=self.evaluate('''const rect=id=>{const r=document.querySelector(id).getBoundingClientRect();return {x:r.x,y:r.y,right:r.right,bottom:r.bottom}};
          return {amount:rect('#today .v95-amount'),recipients:rect('#v81BeneficiaryField'),search:rect('#today .v91-category'),
          dateOutside:!document.getElementById('eDate').closest('#v90Extra'),dateVisible:!!document.getElementById('eDate').getClientRects().length,
          followsAmount:!!(document.querySelector('#today .v95-amount').compareDocumentPosition(document.getElementById('v81BeneficiaryField'))&Node.DOCUMENT_POSITION_FOLLOWING),
          nativeHidden:!document.getElementById('eBeneficiary').getClientRects().length};''')
        self.assertLessEqual(abs(r['amount']['y']-r['recipients']['y']),2)
        self.assertGreaterEqual(r['recipients']['x'],r['amount']['right'])
        self.assertGreaterEqual(r['search']['y'],max(r['amount']['bottom'],r['recipients']['bottom']))
        self.assertTrue(r['dateOutside']);self.assertTrue(r['dateVisible']);self.assertTrue(r['followsAmount']);self.assertTrue(r['nativeHidden'])

    def test_optional_fields_are_folded_and_amount_is_more_prominent(self):
        self.assertFalse(self.page.locator('#v90Extra').evaluate('e=>e.open'))
        for identifier in ['eStore','ePay','eComment','eSubcategory','eAccountId','eIncomeSource']:
            self.assertTrue(self.page.locator('#'+identifier).evaluate('e=>!!e.closest("#v90Extra")'),identifier)
            self.assertFalse(self.page.locator('#'+identifier).is_visible(),identifier)
        self.assertFalse(self.page.locator('#v133FavoritesWrap').evaluate('e=>e.open'))
        self.page.locator('#v90Extra > summary').click()
        self.assertTrue(self.page.locator('#eStore').is_visible())
        r=self.evaluate('''const amount=document.getElementById('eAmount'),optional=document.getElementById('eStore');return {amountHeight:amount.getBoundingClientRect().height,optionalHeight:optional.getBoundingClientRect().height,amountFont:parseFloat(getComputedStyle(amount).fontSize),optionalFont:parseFloat(getComputedStyle(optional).fontSize)};''')
        self.assertGreater(r['amountHeight'],r['optionalHeight']);self.assertGreater(r['amountFont'],r['optionalFont'])

    def test_categories_open_dynamically_and_clear_returns_compact_state(self):
        self.assertFalse(self.page.locator('#v90Quick').is_visible())
        self.page.locator('#v90Search').fill('парковка')
        self.assertTrue(self.page.locator('#v90Quick').is_visible())
        self.assertLessEqual(self.page.locator('#v90Quick button').count(),6)
        self.assertEqual(self.page.locator('#eCategory').input_value(),'')
        self.assertIn('Парковка',self.page.locator('#v90Quick').inner_text())
        self.page.locator('#v90Search').fill('несуществующийпоиск')
        self.assertFalse(self.page.locator('#v90Quick').is_visible())
        self.page.locator('#v91All').click()
        self.assertTrue(self.page.locator('#v90Quick').is_visible())
        self.assertGreater(self.page.locator('#v90Quick button').count(),6)
        self.page.locator('#v90Extra > summary').click()
        self.assertTrue(self.page.locator('#v90Extra').evaluate('e=>e.open'))
        self.page.evaluate('clearEntry()')
        self.assertFalse(self.page.locator('#v90Quick').is_visible())
        self.assertFalse(self.page.locator('#v90Extra').evaluate('e=>e.open'))

    def test_actual_parking_save_uses_selected_chip_date_and_subcategory(self):
        self.page.locator('#eAmount').fill('200')
        self.chip('Автомобиль').click()
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Автомобиль')
        self.assertEqual(self.chip('Автомобиль').get_attribute('aria-pressed'),'true')
        self.page.locator('#v90Search').fill('парковка')
        self.assertEqual(self.page.locator('#eCategory').input_value(),'')
        self.page.locator('#v90Quick [data-cat="Авто и транспорт"]').first.click()
        self.page.locator('#eDate').fill('2026-10-30')
        self.assertFalse(self.page.locator('#v90Extra').evaluate('e=>e.open'))
        self.page.locator('#v90Save').click()
        self.page.wait_for_function('state.entries.length===2&&!v90Saving')
        r=self.evaluate("const e=state.entries.find(e=>e.id!=='synthetic-existing');return {type:e.type,amount:e.amount,beneficiary:e.beneficiary,category:e.category,subcategory:e.subcategory,date:e.date,store:e.store,originalUnchanged:JSON.stringify(state.entries[0])===JSON.parse(originalEntryJSON).map(e=>JSON.stringify(e))[0]};")
        self.assertEqual(r,{'type':'expense','amount':200,'beneficiary':'Автомобиль','category':'Авто и транспорт','subcategory':'Парковка','date':'2026-10-30','store':'','originalUnchanged':True})

    def test_income_and_transfer_modes_keep_date_and_save_their_meaning(self):
        self.page.locator('#eType').select_option('income',force=True)
        self.page.wait_for_function("document.querySelector('#v133IncomeRecipients button[data-v133-recipient]')")
        self.assertTrue(self.page.locator('#eDate').is_visible());self.assertFalse(self.page.locator('#v90Search').is_visible())
        participant=self.page.locator('#v133IncomeRecipients button[data-v133-recipient]').first
        person=participant.get_attribute('data-v133-recipient');participant.click()
        self.page.locator('#eAmount').fill('5000');self.page.locator('#v90Extra > summary').click();self.page.locator('#eIncomeSource').fill('Пропуска')
        self.page.locator('#v90Save').click();self.page.wait_for_function('state.entries.length===2&&!v90Saving')
        r=self.evaluate("const e=state.entries.find(e=>e.type==='income');return {amount:e.amount,who:e.who,source:e.store};")
        self.assertEqual(r,{'amount':5000,'who':person,'source':'Пропуска'})
        self.page.locator('#eType').select_option('transfer',force=True)
        self.assertTrue(self.page.locator('#eDate').is_visible());self.assertFalse(self.page.locator('#v133ExpenseRecipients').is_visible());self.assertFalse(self.page.locator('#v133IncomeRecipients').is_visible())
        self.page.locator('#eAmount').fill('300');self.page.locator('#eFrom').select_option('Карта',force=True);self.page.locator('#eTo').select_option('Накопления',force=True)
        self.page.locator('#v90Save').click();self.page.wait_for_function('state.entries.length===3&&!v90Saving')
        r=self.evaluate("const e=state.entries.find(e=>e.type==='transfer');return {amount:e.amount,from:e.from,to:e.to};")
        self.assertEqual(r,{'amount':300,'from':'Карта','to':'Накопления'})

    def test_repeat_favorite_and_keyboard_update_chips_without_saving(self):
        self.assertTrue(self.evaluate("return v97RepeatEntry('synthetic-existing');"))
        self.assertEqual(self.page.locator('#eAmount').input_value(),'123,45')
        self.assertEqual(self.chip('Общее').get_attribute('aria-pressed'),'true')
        self.page.evaluate('clearEntry()')
        self.assertEqual(self.page.locator('#v133ExpenseRecipients [aria-pressed="true"]').count(),0)
        self.assertTrue(self.evaluate("return v97OpenFavorite('synthetic-favorite');"))
        self.assertEqual(self.page.locator('#eAmount').input_value(),'250')
        self.assertEqual(self.chip('Общее').get_attribute('aria-pressed'),'true')
        self.chip('Сергей').focus();self.page.keyboard.press('Enter')
        self.assertEqual(self.page.locator('#eBeneficiary').input_value(),'Сергей');self.assertEqual(self.chip('Сергей').get_attribute('aria-pressed'),'true')
        self.assertTrue(self.evaluate('return JSON.stringify(state.entries)===originalEntryJSON;'))
        self.page.evaluate('v97ShowFavorites()')
        self.assertTrue(self.page.locator('#v133FavoritesWrap').evaluate('e=>e.open'))

    def test_mobile_order_and_width_keep_primary_controls_usable(self):
        for width in [320,390]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width':width,'height':1000})
                self.page.evaluate('clearEntry()')
                r=self.evaluate('''const amount=document.querySelector('#today .v95-amount').getBoundingClientRect(),who=document.getElementById('v81BeneficiaryField').getBoundingClientRect(),search=document.querySelector('#today .v91-category').getBoundingClientRect();return {overflow:document.documentElement.scrollWidth>document.documentElement.clientWidth+1,amountBottom:amount.bottom,whoTop:who.top,whoBottom:who.bottom,searchTop:search.top,dateVisible:!!document.getElementById('eDate').getClientRects().length};''')
                self.assertFalse(r['overflow']);self.assertGreaterEqual(r['whoTop'],r['amountBottom']);self.assertGreaterEqual(r['searchTop'],r['whoBottom']);self.assertTrue(r['dateVisible'])
                self.assertGreaterEqual(self.chip('Автомобиль').bounding_box()['height'],30)

if __name__=='__main__':unittest.main(verbosity=2)
